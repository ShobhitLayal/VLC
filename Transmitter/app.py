
App · PY
# ================================================================
# VLC TRANSMITTER — signal-lamp dashboard
# ================================================================
# Sends text as Morse pulses of light through an ESP/Arduino over USB
# serial, with a live virtual lamp and a waveform of the pulse train.
#
#   pip install -U streamlit pyserial plotly
#   streamlit run app.py
#
# Optional: put .streamlit/config.toml next to this file so widgets
# (toggle, slider, tabs) pick up the amber theme.
# ================================================================
 
import html
import time
 
import plotly.graph_objects as go
import serial
import serial.tools.list_ports
import streamlit as st
 
st.set_page_config(
    page_title="VLC Transmitter",
    page_icon="🔦",
    layout="wide",
    initial_sidebar_state="expanded",
)
 
# ---------------------------------------------------------------
# Constants
# ---------------------------------------------------------------
 
LAMP = "#FFB431"
LAMP_DIM = "rgba(255,180,49,0.10)"
GRID = "#252F4A"
MUTED = "#8F98AE"
 
DEFAULT_BAUD = 115200
DEFAULT_UNIT_MS = 100
SYNC_ON_UNITS = 9    # long pulse that opens every message (the receiver
SYNC_OFF_UNITS = 3   # measures it to learn the speed)
MAX_LABELLED_LETTERS = 30  # letter labels on the waveform get crowded beyond this
 
MORSE_DICT = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}
 
# ---------------------------------------------------------------
# Session state
# ---------------------------------------------------------------
 
DEFAULT_STATE = {
    "waveform": None,
    "transmission_complete": False,
    "last_message": "",
    "calibration_toggle": False,
    "last_calibration_state": False,
    "serial_connection": None,
    "serial_config": None,
    "last_serial_status": "Idle",
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
 
/* ---------- status pills ---------- */
.pill {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 13px; border-radius: 100px;
    font-size: 13px; font-weight: 600;
    border: 1px solid transparent;
}
.pill::before {
    content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor;
}
.pill.ok   { color: var(--ok);   background: rgba(99,214,169,.09);  border-color: rgba(99,214,169,.28); }
.pill.warn { color: var(--lamp); background: rgba(255,180,49,.09);  border-color: rgba(255,180,49,.30); }
.pill.bad  { color: var(--bad);  background: rgba(255,123,123,.09); border-color: rgba(255,123,123,.28); }
 
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
.stat span { color: var(--muted); font-size: 13px; }
@media (max-width: 700px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
    .stat:nth-child(2) { border-right: 0; }
    .stat:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
}
 
/* ---------- panels (st.container(border=True)) ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--panel);
    border-color: var(--line) !important;
    border-radius: 16px;
}
 
/* ---------- signal lamp ---------- */
.lamp-stage {
    display: flex; flex-direction: column; align-items: center;
    padding: 34px 0 14px;
}
.lamp-housing {
    width: 210px; height: 210px; border-radius: 50%; padding: 14px;
    background: linear-gradient(145deg, #3B4560, #151B2C);
    box-shadow: 0 12px 30px rgba(0,0,0,.45), inset 0 2px 2px rgba(255,255,255,.08);
}
.lamp-lens { position: relative; width: 100%; height: 100%; border-radius: 50%; }
.lamp-lens::after {
    content: ""; position: absolute; inset: 0; border-radius: 50%;
    background: repeating-radial-gradient(
        circle at center, rgba(0,0,0,0) 0 9px, rgba(0,0,0,.14) 9px 11px);
}
.lamp-lens.off {
    background: radial-gradient(circle at 38% 32%, #39415A, #1A2032 62%, #0D1120);
    box-shadow: inset 0 -14px 30px rgba(0,0,0,.6);
}
.lamp-lens.on {
    background: radial-gradient(circle at 40% 34%, #FFF3D0, #FFC44F 32%, #F59A0E 68%, #B86209);
    box-shadow:
        0 0 26px 6px rgba(255,180,49,.85),
        0 0 80px 22px rgba(255,180,49,.45),
        0 0 150px 46px rgba(255,180,49,.20),
        inset 0 5px 16px rgba(255,255,255,.55);
}
.lamp-caption {
    margin-top: 30px; min-height: 26px;
    font-size: 18px; font-weight: 500; color: var(--text);
}
.status-row { display: flex; justify-content: center; margin: 6px 0 10px; min-height: 34px; }
 
/* ---------- morse console ---------- */
.morse-console {
    background: var(--sidebar); border: 1px solid var(--line);
    border-radius: 12px; padding: 16px 18px; min-height: 92px;
    font: 500 20px/2.1 'JetBrains Mono', Consolas, monospace;
    word-break: break-word;
}
.morse-console.empty {
    color: #5A6480; font: 400 15px 'Instrument Sans', sans-serif; line-height: 1.6;
}
.ml {
    display: inline-block; margin-right: .75em; padding: 0 3px;
    border-radius: 5px; color: var(--text);
}
.ml.done { color: var(--lamp); }
.ml.now  { background: var(--lamp); color: #1A1204; }
.ws { color: #55617F; margin: 0 .5em 0 -.1em; }
 
/* ---------- inputs & buttons ---------- */
div[data-baseweb="input"] > div {
    background: var(--panel) !important;
    border: 1px solid var(--line) !important;
    border-radius: 12px !important;
}
div[data-baseweb="input"]:focus-within > div { border-color: var(--lamp) !important; }
div[data-baseweb="input"] input { font-size: 18px !important; padding: 12px 14px !important; }
 
.stButton > button {
    min-height: 48px; border-radius: 12px; font-weight: 600;
    border: 1px solid var(--line); background: transparent; color: var(--text);
}
.stButton > button:hover { border-color: var(--lamp); color: var(--lamp); }
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background: var(--lamp); border-color: var(--lamp); color: #1A1204;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    filter: brightness(1.08); color: #1A1204;
}
.stButton > button:disabled { opacity: .4; }
 
div[data-testid="stProgress"] div[role="progressbar"] > div { background: var(--lamp); }
 
/* ---------- timing table ---------- */
.stMarkdown table { width: 100%; }
.stMarkdown th { color: var(--muted); font-weight: 500; }
</style>
""",
    unsafe_allow_html=True,
)
 
 
def flat(markup):
    """Strip indentation so Markdown never treats HTML as a code block."""
    return "".join(line.strip() for line in markup.splitlines())
 
 
# ---------------------------------------------------------------
# Serial / hardware
# ---------------------------------------------------------------
 
def get_available_ports():
    try:
        return [port.device for port in serial.tools.list_ports.comports()]
    except Exception:
        return []
 
 
def close_serial_connection():
    connection = st.session_state.get("serial_connection")
    if connection is not None:
        try:
            if connection.is_open:
                connection.close()
        except Exception:
            pass
    st.session_state.serial_connection = None
    st.session_state.serial_config = None
 
 
def get_serial_connection(port, baud_rate):
    """
    Reuse one persistent connection so the ESP/Arduino does not reset on
    every Streamlit rerun. Reconnects if the port, baud or link changed.
    """
    if not port:
        raise serial.SerialException("No serial port selected.")
 
    requested = (port, baud_rate)
    connection = st.session_state.get("serial_connection")
 
    if (
        connection is not None
        and st.session_state.get("serial_config") == requested
        and connection.is_open
    ):
        return connection
 
    close_serial_connection()
 
    try:
        connection = serial.Serial(
            port=port, baudrate=baud_rate, timeout=1, write_timeout=1
        )
        time.sleep(1.5)  # many boards reset when the port opens
        connection.reset_input_buffer()
        connection.reset_output_buffer()
 
        st.session_state.serial_connection = connection
        st.session_state.serial_config = requested
        return connection
 
    except (serial.SerialException, OSError) as exc:
        close_serial_connection()
        raise serial.SerialException(str(exc))
 
 
def send_serial_payload(port, baud_rate, payload):
    """Returns (True, None) on success or (False, error_message)."""
    try:
        connection = get_serial_connection(port, baud_rate)
        connection.write(payload.encode("utf-8"))
        connection.flush()
        st.session_state.last_serial_status = "Connected"
        return True, None
    except (serial.SerialException, OSError) as exc:
        close_serial_connection()
        st.session_state.last_serial_status = "Disconnected"
        return False, str(exc)
    except Exception as exc:
        close_serial_connection()
        return False, str(exc)
 
 
# ---------------------------------------------------------------
# Morse / timing
# ---------------------------------------------------------------
 
def normalise_message(message):
    return " ".join(message.upper().strip().split())
 
 
def unsupported_characters(message):
    return sorted({c for c in message if c != " " and c not in MORSE_DICT})
 
 
def build_transmission_events(message, unit_time):
    """
    Text -> timed optical events. Every message opens with a sync pulse
    (9 units on, 3 off) so the receiver can learn the speed. Timing (units):
        dot 1 ON | dash 3 ON | symbol gap 1 OFF
        letter gap 2 OFF | word gap 6 OFF
    Each event: state (1/0), duration (s), label, letter (index), char.
    """
    words = [w for w in message.split() if any(c in MORSE_DICT for c in w)]
    if not words:
        return []
 
    events = [
        {"state": 1, "duration": unit_time * SYNC_ON_UNITS,
         "label": "Sync pulse", "letter": -1, "char": ""},
        {"state": 0, "duration": unit_time * SYNC_OFF_UNITS,
         "label": "Sync gap", "letter": -1},
    ]
    letter_no = -1
 
    for word_index, word in enumerate(words):
        letters = [c for c in word if c in MORSE_DICT]
 
        for letter_index, char in enumerate(letters):
            letter_no += 1
            code = MORSE_DICT[char]
 
            for symbol_index, symbol in enumerate(code):
                is_dot = symbol == "."
                events.append({
                    "state": 1,
                    "duration": unit_time * (1 if is_dot else 3),
                    "label": f"{'Dot' if is_dot else 'Dash'} ({char})",
                    "letter": letter_no,
                    "char": char,
                })
                if symbol_index < len(code) - 1:
                    events.append({
                        "state": 0, "duration": unit_time,
                        "label": "Symbol gap", "letter": letter_no,
                    })
 
            if letter_index < len(letters) - 1:
                events.append({
                    "state": 0, "duration": unit_time * 2,
                    "label": "Letter gap", "letter": letter_no,
                })
 
        if word_index < len(words) - 1 and letter_no >= 0:
            events.append({
                "state": 0, "duration": unit_time * 6,
                "label": "Word gap", "letter": letter_no,
            })
 
    return events
 
 
def total_duration(events):
    return sum(e["duration"] for e in events)
 
 
def count_morse_symbols(message):
    return sum(len(MORSE_DICT[c]) for c in message if c in MORSE_DICT)
 
 
def morse_html(message, current=-1):
    """
    Morse console. Letters before `current` are lit, `current` is
    highlighted. Pass current=-1 for a static view.
    """
    if not message:
        return (
            '<div class="morse-console empty">'
            "Type a message above and its Morse code appears here."
            "</div>"
        )
 
    words_html, index = [], 0
    for word in message.split():
        letters = []
        for char in word:
            if char in MORSE_DICT:
                if current < 0:
                    state = ""
                elif index < current:
                    state = "done"
                elif index == current:
                    state = "now"
                else:
                    state = ""
                letters.append(
                    f'<span class="ml {state}" title="{html.escape(char)}">'
                    f"{MORSE_DICT[char]}</span>"
                )
                index += 1
        if letters:
            words_html.append("".join(letters))
 
    return (
        '<div class="morse-console">'
        + '<span class="ws">/</span>'.join(words_html)
        + "</div>"
    )
 
 
# ---------------------------------------------------------------
# Waveform
# ---------------------------------------------------------------
 
def generate_waveform(events):
    """Step-plot arrays plus the (char, start, end) span of each letter."""
    times, signal = [0.0], [0]
    now = 0.0
    spans = {}
 
    for e in events:
        times.append(now)
        signal.append(e["state"])
        if e["state"] and e["letter"] >= 0:
            span = spans.setdefault(e["letter"], [e["char"], now, now])
            span[2] = now + e["duration"]
        now += e["duration"]
        times.append(now)
        signal.append(e["state"])
 
    if signal[-1] != 0:
        times.append(now)
        signal.append(0)
 
    letters = [tuple(v) for _, v in sorted(spans.items())]
    return times, signal, now, letters
 
 
def create_waveform_figure(times, signal, duration, letters):
    fig = go.Figure(
        go.Scatter(
            x=times, y=signal, mode="lines",
            line=dict(color=LAMP, width=2.6, shape="hv"),
            fill="tozeroy", fillcolor=LAMP_DIM,
            hovertemplate="%{x:.3f} s<extra></extra>",
        )
    )
 
    if len(letters) <= MAX_LABELLED_LETTERS:
        for char, start, end in letters:
            fig.add_annotation(
                x=(start + end) / 2, y=1.14, text=char, showarrow=False,
                font=dict(color=MUTED, size=13),
            )
 
    fig.update_layout(
        height=320,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=58, r=20, t=16, b=48),
        font=dict(family="Instrument Sans, Arial", color=MUTED, size=12),
        hovermode="x",
        showlegend=False,
        xaxis=dict(
            title="Time (seconds)", range=[0, max(duration * 1.03, 1)],
            gridcolor=GRID, linecolor=GRID, zeroline=False,
        ),
        yaxis=dict(
            range=[-0.15, 1.3], tickvals=[0, 1], ticktext=["Off", "On"],
            gridcolor=GRID, linecolor=GRID, zeroline=False,
        ),
    )
    return fig
 
 
# ---------------------------------------------------------------
# Lamp & status widgets
# ---------------------------------------------------------------
 
def pill(text, kind="ok"):
    return f'<span class="pill {kind}">{html.escape(text)}</span>'
 
 
def status_html(text, kind="ok"):
    return flat(f'<div class="status-row">{pill(text, kind)}</div>')
 
 
def lamp_html(active=False, caption="Ready"):
    return flat(
        f"""
        <div class="lamp-stage">
            <div class="lamp-housing">
                <div class="lamp-lens {'on' if active else 'off'}"></div>
            </div>
            <div class="lamp-caption">{html.escape(caption)}</div>
        </div>
        """
    )
 
 
def run_live_visualisation(events, lamp_ph, status_ph, progress_ph, morse_ph, message):
    """
    Play the pulse train in real time. Deadlines are absolute so time
    spent redrawing the page does not accumulate as drift.
    """
    total = total_duration(events)
    elapsed = 0.0
    deadline = time.perf_counter()
    shown_letter = None
 
    for e in events:
        if e["letter"] != shown_letter:
            shown_letter = e["letter"]
            morse_ph.markdown(morse_html(message, shown_letter), unsafe_allow_html=True)
 
        lamp_ph.markdown(lamp_html(bool(e["state"]), e["label"]), unsafe_allow_html=True)
        status_ph.markdown(
            status_html("Transmitting" if e["state"] else "Waiting", "ok" if e["state"] else "warn"),
            unsafe_allow_html=True,
        )
 
        deadline += e["duration"]
        time.sleep(max(0.0, deadline - time.perf_counter()))
 
        elapsed += e["duration"]
        progress_ph.progress(min(elapsed / total, 1.0) if total > 0 else 1.0)
 
    lamp_ph.markdown(lamp_html(False, "Transmission complete"), unsafe_allow_html=True)
    status_ph.markdown(status_html("Complete", "ok"), unsafe_allow_html=True)
    morse_ph.markdown(morse_html(message, 10**6), unsafe_allow_html=True)
    progress_ph.progress(1.0)
 
 
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
            help="The port your ESP/Arduino is plugged into.",
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
        help="Must match the rate set in your microcontroller sketch.",
    )
 
    st.divider()
    st.markdown("### Signal")
 
    unit_time_ms = st.slider(
        "Time unit", min_value=20, max_value=500, value=DEFAULT_UNIT_MS,
        step=10, format="%d ms",
        help="A dot lasts 1 unit and a dash lasts 3. Lower is faster.",
    )
    unit_time = unit_time_ms / 1000.0
 
# ---------------------------------------------------------------
# Header
# ---------------------------------------------------------------
 
head_left, head_right = st.columns([5, 1.6], vertical_alignment="center")
 
with head_left:
    st.markdown(
        flat(
            """
            <div class="app-title">VLC Transmitter</div>
            <div class="app-subtitle">
                Send text as Morse pulses of light through your microcontroller's LED.
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
 
with head_right:
    header_pill = (
        pill("Device found", "ok") if hardware_detected else pill("No device", "bad")
    )
    st.markdown(
        f'<div style="text-align:right">{header_pill}</div>', unsafe_allow_html=True
    )
 
st.write("")
 
# ---------------------------------------------------------------
# Message input and derived values
# ---------------------------------------------------------------
 
message_input = st.text_input(
    "Message",
    placeholder="Type a message, for example: HELLO WORLD",
    label_visibility="collapsed",
)
 
clean_message = normalise_message(message_input)
invalid_chars = unsupported_characters(clean_message)
transmission_events = build_transmission_events(clean_message, unit_time)
estimated_duration = total_duration(transmission_events)
symbol_count = count_morse_symbols(clean_message)
can_send = bool(transmission_events)
words_per_minute = 1.2 / unit_time  # "PARIS" standard = 50 units per word
 
if invalid_chars:
    st.warning(
        "These characters can't be sent and will be skipped: "
        + " ".join(invalid_chars)
        + ". Use letters A–Z and digits 0–9."
    )
 
st.markdown(
    flat(
        f"""
        <div class="stats">
            <div class="stat"><b>{len(clean_message)}</b><span>Characters</span></div>
            <div class="stat"><b>{symbol_count}</b><span>Dots and dashes</span></div>
            <div class="stat"><b>{estimated_duration:.1f} s</b><span>Transmission time</span></div>
            <div class="stat"><b>{words_per_minute:.0f} wpm</b><span>Speed</span></div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)
 
# ---------------------------------------------------------------
# Main body: lamp on the left, controls on the right
# ---------------------------------------------------------------
 
lamp_column, control_column = st.columns([0.9, 1.1], gap="large")
 
calibration_active = st.session_state.calibration_toggle
 
with lamp_column:
    with st.container(border=True):
        st.markdown("#### Lamp")
        lamp_placeholder = st.empty()
        status_placeholder = st.empty()
        progress_placeholder = st.empty()
 
        lamp_placeholder.markdown(
            lamp_html(
                calibration_active,
                "Alignment mode: lamp held on" if calibration_active else "Ready",
            ),
            unsafe_allow_html=True,
        )
        status_placeholder.markdown(
            status_html("Alignment mode on", "warn")
            if calibration_active
            else status_html("Ready", "ok"),
            unsafe_allow_html=True,
        )
 
with control_column:
    with st.container(border=True):
        st.markdown("#### Morse code")
        morse_placeholder = st.empty()
        morse_placeholder.markdown(morse_html(clean_message), unsafe_allow_html=True)
        st.caption("Each group is one letter. A slash separates words.")
 
        send_col, sim_col = st.columns(2)
        with send_col:
            transmit_button = st.button(
                "Send to hardware",
                type="primary",
                width="stretch",
                disabled=not (hardware_detected and can_send),
                help=None if hardware_detected else "Connect a device to enable sending.",
            )
        with sim_col:
            simulation_button = st.button(
                "Preview on screen",
                width="stretch",
                disabled=not can_send,
                help="Plays the pulses on the virtual lamp only.",
            )
 
    with st.container(border=True):
        st.markdown("#### Alignment mode")
        st.caption(
            "Holds the physical LED on so you can aim the transmitter "
            "at the receiver. Turn it off before sending."
        )
 
        calibration_state = st.toggle(
            "Hold LED on",
            key="calibration_toggle",
            disabled=not hardware_detected,
        )
 
        # Send a command only when the toggle actually changes:
        # "[" = continuous on, "]" = back to normal.
        if calibration_state != st.session_state.last_calibration_state:
            command = "[" if calibration_state else "]"
            ok, error = send_serial_payload(selected_port, baud_rate, command)
            st.session_state.last_calibration_state = calibration_state
 
            if ok:
                st.toast(
                    "LED held on." if calibration_state else "LED back to normal.",
                    icon="💡",
                )
            else:
                st.error(f"Couldn't reach the device. {error}")
 
# ---------------------------------------------------------------
# Store waveform for the chart tab
# ---------------------------------------------------------------
 
if clean_message and can_send:
    w_time, w_signal, w_duration, w_letters = generate_waveform(transmission_events)
    st.session_state.waveform = {
        "time": w_time,
        "signal": w_signal,
        "duration": w_duration,
        "letters": w_letters,
        "message": clean_message,
    }
 
# ---------------------------------------------------------------
# Actions
# ---------------------------------------------------------------
 
if transmit_button:
    if calibration_state:
        st.warning("Turn off alignment mode before sending a message.")
    elif not selected_port:
        st.error("No device found. Plug in the board and refresh the ports.")
    else:
        status_placeholder.markdown(status_html("Sending", "warn"), unsafe_allow_html=True)
        # "@<ms>\n" tells the ESP32 the time unit, then the message follows.
        payload = f"@{unit_time_ms}\n{clean_message}"
        ok, error = send_serial_payload(selected_port, baud_rate, payload)
 
        if ok:
            st.session_state.last_message = clean_message
            st.session_state.transmission_complete = False
            run_live_visualisation(
                transmission_events, lamp_placeholder, status_placeholder,
                progress_placeholder, morse_placeholder, clean_message,
            )
            st.session_state.transmission_complete = True
        else:
            lamp_placeholder.markdown(lamp_html(False, "Device unreachable"), unsafe_allow_html=True)
            status_placeholder.markdown(status_html("Send failed", "bad"), unsafe_allow_html=True)
            st.error(
                "The message wasn't sent. The device may have been unplugged. "
                f"Details: {error}"
            )
 
if simulation_button and can_send:
    if calibration_state:
        st.info(
            "Alignment mode is on, so the physical LED may stay lit. "
            "The preview still plays on the virtual lamp."
        )
    st.session_state.transmission_complete = False
    run_live_visualisation(
        transmission_events, lamp_placeholder, status_placeholder,
        progress_placeholder, morse_placeholder, clean_message,
    )
    st.session_state.transmission_complete = True
 
# ---------------------------------------------------------------
# Waveform and reference
# ---------------------------------------------------------------
 
st.write("")
tab_wave, tab_ref = st.tabs(["Waveform", "Timing and protocol"])
 
with tab_wave:
    stored = st.session_state.waveform
    if stored:
        st.caption(
            f"Pulse train for “{stored['message']}”. On means the LED is lit. "
            "Scroll to zoom, drag to pan."
        )
        st.plotly_chart(
            create_waveform_figure(
                stored["time"], stored["signal"], stored["duration"], stored["letters"]
            ),
            config={
                "displaylogo": False,
                "scrollZoom": True,
                "modeBarButtonsToRemove": ["lasso2d", "select2d"],
            },
        )
    else:
        st.info("Type a message to see its waveform here.")
 
with tab_ref:
    ref_left, ref_right = st.columns(2, gap="large")
 
    with ref_left:
        st.markdown(
            f"""
| Element | Units | Duration |
|---|---|---|
| Dot (lamp on) | 1 | {unit_time_ms} ms |
| Dash (lamp on) | 3 | {unit_time_ms * 3} ms |
| Gap between symbols | 1 | {unit_time_ms} ms |
| Gap between letters | 2 | {unit_time_ms * 2} ms |
| Gap between words | 6 | {unit_time_ms * 6} ms |
| Sync pulse (starts a message) | 9 on, 3 off | {unit_time_ms * 9} ms on, {unit_time_ms * 3} ms off |
"""
        )
 
    with ref_right:
        st.markdown(
            f"""
**Serial link**
 
- Port: `{selected_port or "none"}`
- Baud rate: `{baud_rate}`
- Speed: `@<ms>` and a newline, sent before every message
- Message: uppercase text, opened by a sync pulse
- Alignment on: send `[`
- Alignment off: send `]`
"""
        )
 
Claude finished the response
