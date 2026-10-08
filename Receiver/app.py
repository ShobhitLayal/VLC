# ================================================================
# VLC RECEIVER: dashboard for the ESP8266 + LDR receiver
# ================================================================
# Shows the decoded message, the live light level and the link state.
# Pairs with vlc_receiver.ino (see that file for the serial protocol).
#
#   pip install -U streamlit pyserial plotly
#   streamlit run app.py
# ================================================================

import html
import math
import time

import plotly.graph_objects as go
import serial
import serial.tools.list_ports
import streamlit as st

st.set_page_config(
    page_title="VLC Receiver",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------
# Constants
# ---------------------------------------------------------------

LAMP = "#FFB431"
GRID = "#252F4A"
MUTED = "#8F98AE"

DEFAULT_BAUD = 115200
DEFAULT_MIN_SWING = 30     # the laser raises the LDR reading by at least 50
ADC_MAX = 1023
TELEMETRY_HZ = 20
TRACE_POINTS = 200          # 10 seconds of light level
LOG_LIMIT = 20000           # characters kept in the log
STALE_SECONDS = 2.0         # no telemetry for this long = no response
POLL_SECONDS = 0.25

# ---------------------------------------------------------------
# Session state
# ---------------------------------------------------------------

DEFAULT_STATE = {
    "listening": False,
    "serial_conn": None,
    "serial_config": None,
    "rx_buffer": "",
    "log": "",
    "chars": 0,
    "messages": 0,
    "unit_ms": None,
    "trace": [],
    "tele": None,
    "last_rx": None,
    "sent_swing": None,
    "last_error": None,
}
for _key, _value in DEFAULT_STATE.items():
    st.session_state.setdefault(_key, _value)

# ---------------------------------------------------------------
# Styling
# ---------------------------------------------------------------

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Instrument+Sans:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap');

:root {
    --bg: #10172A;
    --sidebar: #0C1222;
    --panel: #161F35;
    --line: #2A3554;
    --text: #ECE7DB;
    --muted: #8F98AE;
    --lamp: #FFB431;
    --ok: #63D6A9;
    --bad: #FF7B7B;
}

html, body, [class*="css"] {
    font-family: 'Instrument Sans', -apple-system, 'Segoe UI', sans-serif;
}
.stApp { background: var(--bg); color: var(--text); }
.block-container { max-width: 1320px; padding-top: 2rem; padding-bottom: 3rem; }
#MainMenu, footer { visibility: hidden; }

section[data-testid="stSidebar"] {
    background: var(--sidebar);
    border-right: 1px solid var(--line);
}

h3, h4 {
    font-family: 'Bricolage Grotesque', 'Instrument Sans', sans-serif !important;
    letter-spacing: -0.01em;
    color: var(--text);
}

/* ---------- header ---------- */
.app-title {
    font-family: 'Bricolage Grotesque', sans-serif;
    font-size: 42px; font-weight: 700; letter-spacing: -0.03em;
    line-height: 1.05; color: var(--text);
}
.app-subtitle { color: var(--muted); font-size: 15px; margin-top: 6px; }

/* ---------- pills ---------- */
.pill {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 13px; border-radius: 100px;
    font-size: 13px; font-weight: 600; border: 1px solid transparent;
}
.pill::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor; }
.pill.ok   { color: var(--ok);   background: rgba(99,214,169,.09);  border-color: rgba(99,214,169,.28); }
.pill.warn { color: var(--lamp); background: rgba(255,180,49,.09);  border-color: rgba(255,180,49,.30); }
.pill.bad  { color: var(--bad);  background: rgba(255,123,123,.09); border-color: rgba(255,123,123,.28); }
.pill.idle { color: var(--muted); background: rgba(143,152,174,.08); border-color: rgba(143,152,174,.25); }

/* ---------- stat strip ---------- */
.stats {
    display: grid; grid-template-columns: repeat(4, 1fr);
    background: var(--panel); border: 1px solid var(--line);
    border-radius: 14px; overflow: hidden; margin: 6px 0 22px;
}
.stat { padding: 14px 20px; border-right: 1px solid var(--line); }
.stat:last-child { border-right: 0; }
.stat b {
    display: block; font-family: 'Bricolage Grotesque', sans-serif;
    font-size: 28px; font-weight: 600; color: var(--text); line-height: 1.15;
}
.stat b.ok { color: var(--ok); }
.stat b.warn { color: var(--lamp); }
.stat b.bad { color: var(--bad); }
.stat b.idle { color: var(--muted); }
.stat span { color: var(--muted); font-size: 13px; }
@media (max-width: 700px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
    .stat:nth-child(2) { border-right: 0; }
    .stat:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
}

/* ---------- panels ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--panel);
    border-color: var(--line) !important;
    border-radius: 16px;
}

/* ---------- light gauge ---------- */
.gauge { display: flex; flex-direction: column; align-items: center; padding: 10px 0 2px; }
.gauge svg { width: 230px; height: 230px; overflow: visible; }
.gauge .lit { filter: drop-shadow(0 0 9px rgba(255,180,49,.75)); }
.gauge .pct {
    font-family: 'Bricolage Grotesque', sans-serif; font-size: 44px; font-weight: 700;
    fill: var(--text);
}
.gauge .cap { font-size: 13px; fill: var(--muted); }

.meter-row { display: flex; justify-content: space-between; font-size: 13px; color: var(--muted); margin: 14px 0 6px; }
.meter-row b { color: var(--text); font-weight: 600; }
.meter { position: relative; height: 8px; border-radius: 8px; background: var(--sidebar); border: 1px solid var(--line); }
.meter .fill { height: 100%; border-radius: 8px; background: var(--lamp); }
.meter .mark { position: absolute; top: -4px; width: 2px; height: 14px; background: var(--muted); }
.hint { color: var(--muted); font-size: 13px; line-height: 1.5; margin-top: 12px; }
.hint.warn { color: var(--lamp); }

/* ---------- message terminal ---------- */
.terminal {
    display: flex; flex-direction: column-reverse;
    background: var(--sidebar); border: 1px solid var(--line);
    border-radius: 12px; padding: 18px 20px;
    min-height: 300px; max-height: 340px; overflow-y: auto;
}
.term-inner {
    font: 500 22px/1.75 'JetBrains Mono', Consolas, monospace;
    letter-spacing: .06em; color: var(--text); word-break: break-word;
}
.terminal.empty .term-inner {
    color: #5A6480; font: 400 16px/1.6 'Instrument Sans', sans-serif; letter-spacing: 0;
}
.unk { color: var(--bad); }
.cursor {
    display: inline-block; width: .55em; height: 1.05em; margin-left: 3px;
    background: var(--lamp); vertical-align: text-bottom;
    animation: blink 1s step-end infinite;
}
@keyframes blink { 50% { opacity: 0; } }

/* ---------- buttons ---------- */
.stButton > button, .stDownloadButton > button {
    min-height: 48px; border-radius: 12px; font-weight: 600;
    border: 1px solid var(--line); background: transparent; color: var(--text);
}
.stButton > button:hover, .stDownloadButton > button:hover { border-color: var(--lamp); color: var(--lamp); }
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background: var(--lamp); border-color: var(--lamp); color: #1A1204;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover { filter: brightness(1.08); color: #1A1204; }
.stButton > button:disabled, .stDownloadButton > button:disabled { opacity: .4; }

.stMarkdown table { width: 100%; }
.stMarkdown th { color: var(--muted); font-weight: 500; }
</style>
""",
    unsafe_allow_html=True,
)


def flat(markup):
    """Strip indentation so Markdown never treats HTML as a code block."""
    return "".join(line.strip() for line in markup.splitlines())


def pill(text, kind="ok"):
    return f'<span class="pill {kind}">{html.escape(text)}</span>'


# ---------------------------------------------------------------
# Serial
# ---------------------------------------------------------------

def get_available_ports():
    try:
        return [port.device for port in serial.tools.list_ports.comports()]
    except Exception:
        return []


def close_serial_connection():
    connection = st.session_state.serial_conn
    if connection is not None:
        try:
            if connection.is_open:
                connection.close()
        except Exception:
            pass
    st.session_state.serial_conn = None
    st.session_state.serial_config = None


def get_serial_connection(port, baud_rate):
    """Reuse one connection; reopen if the port or baud rate changed."""
    if not port:
        raise serial.SerialException("No serial port selected.")

    requested = (port, baud_rate)
    connection = st.session_state.serial_conn
    if (
        connection is not None
        and st.session_state.serial_config == requested
        and connection.is_open
    ):
        return connection

    close_serial_connection()
    try:
        connection = serial.Serial(port=port, baudrate=baud_rate, timeout=0.02, write_timeout=1)
        time.sleep(1.5)  # the ESP8266 resets when the port opens
        connection.reset_input_buffer()

        st.session_state.serial_conn = connection
        st.session_state.serial_config = requested
        st.session_state.rx_buffer = ""
        st.session_state.tele = None
        st.session_state.last_rx = None
        st.session_state.trace = []
        st.session_state.sent_swing = None
        return connection
    except (serial.SerialException, OSError) as exc:
        close_serial_connection()
        raise serial.SerialException(str(exc))


def send_command(text):
    """Send one newline-terminated command to the receiver."""
    connection = st.session_state.serial_conn
    if connection is None or not connection.is_open:
        return
    try:
        connection.write((text + "\n").encode("ascii"))
        connection.flush()
    except (serial.SerialException, OSError):
        close_serial_connection()
        st.session_state.listening = False
        st.session_state.last_error = "The receiver stopped responding."


def read_serial():
    connection = st.session_state.serial_conn
    if connection is None or not connection.is_open:
        return ""
    waiting = connection.in_waiting
    if waiting <= 0:
        return ""
    return connection.read(waiting).decode("utf-8", errors="ignore").replace("\r", "")


# ---------------------------------------------------------------
# Receiver protocol
# ---------------------------------------------------------------

def ingest(chunk):
    """Parse the receiver's line protocol into session state."""
    s = st.session_state
    s.rx_buffer += chunk
    *lines, rest = s.rx_buffer.split("\n")
    s.rx_buffer = rest[-200:]

    for raw in lines:
        kind, _, payload = raw.strip().partition(",")

        if kind == "L":
            try:
                level, thr, swing, lit, phase = (int(x) for x in payload.split(","))
            except ValueError:
                continue
            s.tele = {"level": level, "thr": thr, "swing": swing, "lit": bool(lit), "phase": phase}
            s.trace.append((level, thr))
            if len(s.trace) > TRACE_POINTS:
                s.trace = s.trace[-TRACE_POINTS:]
            s.last_rx = time.time()

        elif kind == "C" and payload:
            s.log += payload[0]
            s.chars += 1

        elif kind == "W":
            s.log += " "

        elif kind == "B":
            try:
                s.unit_ms = int(payload)
            except ValueError:
                pass
            s.messages += 1
            if s.log and not s.log.endswith("\n"):
                s.log += "\n"

        elif kind == "E":
            if s.log and not s.log.endswith("\n"):
                s.log += "\n"

        # Anything else (boot noise, the hello line) is ignored.

    s.log = s.log[-LOG_LIMIT:]


def link_state(min_swing):
    """(label, kind) describing the link right now."""
    s = st.session_state
    if not s.listening:
        return "Paused", "idle"
    if s.last_rx is None or time.time() - s.last_rx > STALE_SECONDS:
        return "No response", "bad"
    tele = s.tele
    if tele["phase"] == 2:
        return "Receiving", "ok"
    if tele["phase"] == 1:
        return "Syncing", "ok"
    if tele["swing"] >= min_swing:
        return "Waiting for sync", "warn"
    return "No light signal", "idle"


def clear_log():
    st.session_state.log = ""
    st.session_state.chars = 0
    st.session_state.messages = 0


def reset_detector():
    send_command("R")
    st.session_state.tele = None
    st.session_state.trace = []


# ---------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------

def gauge_html(level, thr, lit):
    """Ring showing the light level, with a tick at the decision threshold."""
    radius, cx = 78, 100
    circumference = 2 * math.pi * radius
    frac = max(0.0, min(level / ADC_MAX, 1.0))

    angle = math.radians(max(0.0, min(thr / ADC_MAX, 1.0)) * 360 - 90)
    x1, y1 = cx + (radius - 12) * math.cos(angle), cx + (radius - 12) * math.sin(angle)
    x2, y2 = cx + (radius + 12) * math.cos(angle), cx + (radius + 12) * math.sin(angle)

    ring_color = LAMP if lit else "#6B7694"
    return flat(
        f"""
        <div class="gauge"><svg viewBox="0 0 200 200" class="{'lit' if lit else ''}">
        <circle cx="100" cy="100" r="{radius}" fill="none" stroke="#202A44" stroke-width="14"/>
        <circle cx="100" cy="100" r="{radius}" fill="none" stroke="{ring_color}" stroke-width="14"
            stroke-linecap="round" stroke-dasharray="{frac * circumference:.1f} {circumference:.1f}"
            transform="rotate(-90 100 100)"/>
        <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#ECE7DB" stroke-width="2.5"/>
        <text x="100" y="108" text-anchor="middle" class="pct">{frac * 100:.0f}%</text>
        <text x="100" y="132" text-anchor="middle" class="cap">Light level</text>
        </svg></div>
        """
    )


def strength_html(swing, min_swing):
    frac = max(0.0, min(swing / (min_swing * 4), 1.0))
    if swing < min_swing:
        label = "No signal"
    elif swing < 2 * min_swing:
        label = "Weak"
    elif swing < 4 * min_swing:
        label = "Good"
    else:
        label = "Strong"
    return flat(
        f"""
        <div class="meter-row"><span>Signal strength</span><b>{label}</b></div>
        <div class="meter"><div class="fill" style="width:{frac * 100:.0f}%"></div>
        <div class="mark" style="left:25%"></div></div>
        """
    )


def terminal_html(log, listening):
    if not log:
        text = "Waiting for a message..." if listening else "Press Start listening to begin."
        return (
            '<div class="terminal empty"><div class="term-inner">'
            f'{text}<span class="cursor"></span></div></div>'
        )
    body = html.escape(log[-1500:]).replace("?", '<span class="unk">?</span>').replace("\n", "<br>")
    cursor = '<span class="cursor"></span>' if listening else ""
    return f'<div class="terminal"><div class="term-inner">{body}{cursor}</div></div>'


def trace_figure(trace):
    levels = [p[0] for p in trace]
    thresholds = [p[1] for p in trace]
    n = len(trace)
    seconds = [(i - (n - 1)) / TELEMETRY_HZ for i in range(n)]

    low, high = min(levels), max(levels)
    if high - low < 100:
        middle = (high + low) / 2
        low, high = middle - 50, middle + 50
    pad = (high - low) * 0.1

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=seconds, y=thresholds, mode="lines", name="Threshold",
        line=dict(color=MUTED, width=1.5, dash="dash"),
        hovertemplate="threshold %{y}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=seconds, y=levels, mode="lines", name="Light level",
        line=dict(color=LAMP, width=2.4),
        hovertemplate="level %{y}<extra></extra>",
    ))
    fig.update_layout(
        height=260,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=54, r=16, t=10, b=44),
        font=dict(family="Instrument Sans, Arial", color=MUTED, size=12),
        showlegend=False, hovermode="x",
        xaxis=dict(title="Seconds ago", range=[-TRACE_POINTS / TELEMETRY_HZ, 0],
                   gridcolor=GRID, linecolor=GRID, zeroline=False),
        yaxis=dict(title="ADC reading", range=[max(0, low - pad), min(ADC_MAX, high + pad)],
                   gridcolor=GRID, linecolor=GRID, zeroline=False),
    )
    return fig


# ---------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------

with st.sidebar:
    st.markdown("### Connection")

    available_ports = get_available_ports()
    hardware_detected = bool(available_ports)

    if hardware_detected:
        selected_port = st.selectbox(
            "Serial port", available_ports,
            help="The port your ESP8266 is plugged into.",
        )
        st.markdown(pill("Device found", "ok"), unsafe_allow_html=True)
    else:
        selected_port = None
        st.markdown(pill("No device found", "bad"), unsafe_allow_html=True)
        st.caption("Plug in the board, then refresh.")

    st.button("Refresh ports", width="stretch")

    baud_options = [9600, 19200, 38400, 57600, 115200]
    baud_rate = st.selectbox(
        "Baud rate", baud_options, index=baud_options.index(DEFAULT_BAUD),
        help="Must match the rate in vlc_receiver.ino.",
    )

    st.divider()
    st.markdown("### Detection")

    min_swing = st.slider(
        "Minimum contrast", min_value=10, max_value=200, value=DEFAULT_MIN_SWING,
        step=5, key="min_swing", format="%d counts",
        help="How much the reading must rise before light counts as on. The laser "
             "should add at least 50, so 30 leaves some margin. Raise it if noise "
             "causes false pulses; lower it if the signal is weak.",
    )

    st.button(
        "Reset detector", width="stretch", on_click=reset_detector,
        disabled=not st.session_state.listening,
        help="Forgets the learned dark and bright levels.",
    )

# ---------------------------------------------------------------
# Header and controls
# ---------------------------------------------------------------

head_left, head_right = st.columns([5, 1.6], vertical_alignment="center")

with head_left:
    st.markdown(
        flat(
            """
            <div class="app-title">VLC Receiver</div>
            <div class="app-subtitle">
                Decode Morse pulses of laser light picked up by your LDR.
            </div>
            """
        ),
        unsafe_allow_html=True,
    )

with head_right:
    header_pill = pill("Device found", "ok") if hardware_detected else pill("No device", "bad")
    st.markdown(f'<div style="text-align:right">{header_pill}</div>', unsafe_allow_html=True)

st.write("")

button_col, note_col = st.columns([1, 3], vertical_alignment="center")

with button_col:
    if st.session_state.listening:
        stop_clicked = st.button("Stop listening", width="stretch")
        start_clicked = False
    else:
        start_clicked = st.button(
            "Start listening", type="primary", width="stretch",
            disabled=not hardware_detected,
        )
        stop_clicked = False

with note_col:
    st.caption(
        "Aim the laser at the LDR. The receiver learns the speed from each "
        "message, so there is nothing to match. Use a time unit of 100 ms or more."
    )

if stop_clicked:
    close_serial_connection()
    st.session_state.listening = False
    st.rerun()

if start_clicked:
    st.session_state.last_error = None
    st.session_state.listening = True

# Keep the connection alive across reruns; reconnect if the port changed.
if st.session_state.listening:
    try:
        with st.spinner("Connecting to the receiver..."):
            get_serial_connection(selected_port, baud_rate)
        if st.session_state.sent_swing != min_swing:
            send_command("?")
            send_command(f"M{min_swing}")
            st.session_state.sent_swing = min_swing
    except serial.SerialException as exc:
        st.session_state.listening = False
        st.session_state.last_error = str(exc)

if st.session_state.last_error:
    st.error(f"Couldn't reach the receiver. {st.session_state.last_error}")

# ---------------------------------------------------------------
# Live view (refreshes by itself while listening)
# ---------------------------------------------------------------

def live_view():
    s = st.session_state

    if s.listening and s.serial_conn is not None:
        try:
            chunk = read_serial()
            if chunk:
                ingest(chunk)
        except (serial.SerialException, OSError) as exc:
            close_serial_connection()
            s.listening = False
            s.last_error = f"The device was unplugged or the port became unavailable ({exc})."
            st.rerun()

    label, kind = link_state(min_swing)
    unit = f"{s.unit_ms} ms" if s.unit_ms else "-"
    speed = f"{1.2 / (s.unit_ms / 1000):.0f} wpm" if s.unit_ms else ""

    st.markdown(
        flat(
            f"""
            <div class="stats">
                <div class="stat"><b>{s.chars}</b><span>Characters received</span></div>
                <div class="stat"><b>{s.messages}</b><span>Messages</span></div>
                <div class="stat"><b>{unit}</b><span>Time unit {('(' + speed + ')') if speed else ''}</span></div>
                <div class="stat"><b class="{kind}">{label}</b><span>Link</span></div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )

    sensor_col, message_col = st.columns([0.8, 1.2], gap="large")

    with sensor_col:
        with st.container(border=True):
            st.markdown("#### Sensor")
            tele = s.tele or {"level": 0, "thr": 0, "swing": 0, "lit": False, "phase": 0}

            st.markdown(gauge_html(tele["level"], tele["thr"], tele["lit"]), unsafe_allow_html=True)
            st.markdown(strength_html(tele["swing"], min_swing), unsafe_allow_html=True)

            if s.tele and tele["level"] >= 1015:
                st.markdown(
                    '<div class="hint warn">The reading is at the ADC limit. '
                    "Use a smaller fixed resistor or shade the LDR from room light.</div>",
                    unsafe_allow_html=True,
                )
            elif s.listening and kind == "bad":
                st.markdown(
                    '<div class="hint warn">Nothing is coming from the board. '
                    "Check that vlc_receiver.ino is flashed and the baud rate is 115200.</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="hint">The tick marks the level where light counts as on.</div>',
                    unsafe_allow_html=True,
                )

    with message_col:
        with st.container(border=True):
            st.markdown("#### Received message")
            st.markdown(terminal_html(s.log, s.listening), unsafe_allow_html=True)
            if "?" in s.log:
                st.caption("A red ? is a letter that could not be read.")

            save_col, clear_col = st.columns(2)
            with save_col:
                st.download_button(
                    "Save log", data=s.log, file_name="vlc_received.txt",
                    mime="text/plain", width="stretch", disabled=not s.log, key="save_log",
                )
            with clear_col:
                st.button(
                    "Clear", width="stretch", on_click=clear_log,
                    disabled=not s.log, key="clear_log",
                )

    with st.container(border=True):
        st.markdown("#### Signal trace")
        if len(s.trace) >= 2:
            st.plotly_chart(
                trace_figure(s.trace),
                config={"displaylogo": False, "displayModeBar": False},
                key="trace_chart",
            )
            st.caption("Amber is the light level. The dashed line is the on/off threshold.")
        else:
            st.info("The light level appears here once the receiver is listening.")


live = st.fragment(run_every=POLL_SECONDS if st.session_state.listening else None)(live_view)
live()

# ---------------------------------------------------------------
# Setup guide
# ---------------------------------------------------------------

with st.expander("Wiring and setup"):
    left, right = st.columns(2, gap="large")

    with left:
        st.markdown(
            """
**Wiring (voltage divider)**

- 3V3 to one leg of the **LDR**
- Other leg of the LDR to **A0**
- A fixed resistor (about 10 kΩ) from **A0** to **GND**
- The reading must **rise** when the laser hits the LDR. If it falls, swap the LDR and the resistor.

**Choosing the resistor**

The most swing comes from a resistor close to the LDR's resistance in
room light. If the gauge sits at 100% before the laser is even on, use a
smaller one. Power the divider from 3.3 V, not 5 V.
"""
        )

    with right:
        st.markdown(
            """
**How the link works**

- Each message opens with a long sync pulse that sets the speed
- An LDR switches off slower than it switches on. The sync pulse also measures that skew, and it is corrected automatically
- Base and laser levels are tracked on their own, so changing the room light is fine

**If nothing decodes**

- Aim the laser at the LDR and watch the signal strength. It should rise by 50 or more.
- If letters come out wrong or the message is cut short, raise the time unit on the transmitter (150 to 200 ms for a slow LDR)
- Raise the minimum contrast if you see false pulses
"""
        )