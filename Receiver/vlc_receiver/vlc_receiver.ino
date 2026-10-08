// ================================================================
// VLC RECEIVER: ESP8266 firmware for the Streamlit receiver dashboard
// ================================================================
// Hardware (LDR voltage divider, 5 V supply):
//   5 V -> LDR -> A0 -> fixed resistor (about 1k) -> GND
//   The reading must RISE when the laser hits the LDR. If it falls,
//   swap the LDR and the resistor. The firmware expects a base reading
//   that rises by at least 50 counts under the laser.
//   NodeMCU / Wemos boards read 0-5 V on A0 (0-1023).
//
// How it works:
//   1. Sample A0 at 1 kHz, 4 reads per sample, then a 10-sample moving
//      average to smooth out noise.
//   2. Track the dark and bright levels and put the decision threshold
//      halfway between them, with hysteresis and debouncing.
//   3. Every message from vlc_transmitter.ino opens with a sync pulse
//      (9 units on, 3 off). The time unit is measured from it as
//      (on + off) / 12, so no speed setting is needed here.
//   4. An LDR falls slower than it rises, which stretches every pulse
//      and shortens every gap. The sync pulse reveals that skew,
//      (on - 3 * off) / 4, and it is removed from every later timing.
//   5. Pulses and gaps are classified in units, then decoded to text.
//
// Speed: an LDR needs time to react. Use a time unit of 100 ms or more
// on the transmitter (150-200 ms for a slow LDR).
//
// Serial output (115200 baud, one line each):
//   H,VLC-RX,1,<min swing>     hello, reply to "?"
//   B,<unit ms>                a message starts (sent with its first letter)
//   C,<char>                   decoded letter or digit ("?" = unreadable)
//   W                          word space
//   E                          message ended
//   L,<level>,<thr>,<swing>,<lit>,<phase>   20 times a second
//       level, thr, swing: 0-1023 counts | lit: 0 or 1
//       phase: 0 waiting for sync, 1 syncing, 2 receiving
//
// Serial input (newline terminated):
//   R          reset the detector
//   M<counts>  minimum swing between dark and bright, 8-300 (default 30)
//   ?          reply with the hello line
// ================================================================

#include <Arduino.h>
#include <ESP8266WiFi.h>

// ---------------- configuration ----------------
const uint32_t BAUD_RATE = 115200;

const uint32_t SAMPLE_US      = 1000;    // 1 kHz
const uint8_t  OVERSAMPLE     = 4;       // ADC reads averaged per sample
const uint8_t  BOX_LEN        = 10;      // moving average: 10 ms
const uint8_t  DEBOUNCE_TICKS = 3;       // an edge must hold for 3 samples
const float    ENV_DECAY      = 1.0f / 8000.0f;  // envelope forgets in ~8 s
const uint32_t TELEMETRY_US   = 50000;   // 20 Hz

const uint32_t UNIT_MIN_US     = 15000UL;
const uint32_t UNIT_MAX_US     = 600000UL;
const uint32_t UNIT_DEFAULT_US = 100000UL;

// A sync pulse is 9 units long
const uint32_t SYNC_MIN_US = 9UL * UNIT_MIN_US;
const uint32_t SYNC_MAX_US = 9UL * UNIT_MAX_US;

const float DEFAULT_MIN_SWING = 30.0f;   // the laser adds at least 50

// ---------------- Morse tables (same as the transmitter) ----------------
const char* const LETTERS[26] = {
  ".-",   "-...", "-.-.", "-..",  ".",    "..-.", "--.",  "....", "..",
  ".---", "-.-",  ".-..", "--",   "-.",   "---",  ".--.", "--.-", ".-.",
  "...",  "-",    "..-",  "...-", ".--",  "-..-", "-.--", "--.."
};

const char* const DIGITS[10] = {
  "-----", ".----", "..---", "...--", "....-",
  ".....", "-....", "--...", "---..", "----."
};

// ---------------- state ----------------
enum Phase : uint8_t { PHASE_IDLE = 0, PHASE_SYNC = 1, PHASE_MESSAGE = 2 };
Phase phase = PHASE_IDLE;

// signal chain
uint16_t boxBuf[BOX_LEN];
uint32_t boxSum = 0;
uint8_t  boxIdx = 0;
float    level = 0, hi = 0, lo = 0, thr = 0, swing = 0;
float    minSwing = DEFAULT_MIN_SWING;
bool     signalPresent = false;   // enough contrast between dark and bright
bool     lit = false;             // debounced on/off decision
bool     pending = false;
uint8_t  pendCount = 0;
uint32_t pendSinceUs = 0;

// edge timing
uint32_t lastRiseUs = 0;
uint32_t lastFallUs = 0;

// decoder
uint32_t unitUs = UNIT_DEFAULT_US;
uint32_t syncOnUs = 0;
int32_t  biasUs = 0;       // how much longer ON reads than it should (and OFF shorter)
char     sym[8];
uint8_t  symLen = 0;
bool     symOverflow = false;
bool     msgStarted = false;

// scheduling and serial input
uint32_t nextSampleUs = 0;
uint32_t lastTeleUs = 0;
char     cmd[16];
uint8_t  cmdLen = 0;

// ---------------- prototypes ----------------
uint16_t readAdc();
void sampleTick(uint32_t now);
void processEdge(bool rising, uint32_t t);
void onPulse(uint32_t onUs);
void onGap(uint32_t offUs);
void checkTimeouts(uint32_t now);
void addSymbol(char c);
void flushLetter();
void endMessage();
char decodeSymbols();
void emitChar(char c);
void resetDetector();
void pollCommands();
void handleCommand();
void sendHello();
uint32_t correctedOn(uint32_t onUs);
uint32_t correctedOff(uint32_t offUs);

// ================================================================

void setup() {
  // Wi-Fi radio activity adds noise to the ADC, so switch it off.
  WiFi.persistent(false);
  WiFi.mode(WIFI_OFF);
  WiFi.forceSleepBegin();
  delay(1);

  Serial.begin(BAUD_RATE);

  // Fill the moving average so the first samples are valid.
  for (uint8_t i = 0; i < BOX_LEN; i++) {
    boxBuf[i] = readAdc();
    boxSum += boxBuf[i];
    delay(1);
  }
  level = (float)boxSum / BOX_LEN;
  hi = lo = thr = level;

  Serial.println();
  sendHello();

  nextSampleUs = micros() + SAMPLE_US;
  lastTeleUs = micros();
}

void loop() {
  uint32_t now = micros();

  if ((int32_t)(now - nextSampleUs) >= 0) {
    nextSampleUs += SAMPLE_US;
    if ((int32_t)(now - nextSampleUs) >= 0) nextSampleUs = now + SAMPLE_US;  // fell behind
    sampleTick(now);
  }

  pollCommands();

  if ((uint32_t)(now - lastTeleUs) >= TELEMETRY_US) {
    lastTeleUs = now;
    Serial.printf("L,%d,%d,%d,%d,%d\n",
                  (int)(level + 0.5f), (int)(thr + 0.5f), (int)(swing + 0.5f),
                  lit ? 1 : 0, (int)phase);
  }
}

// ================================================================
// Signal chain
// ================================================================

uint16_t readAdc() {
  uint32_t sum = 0;
  for (uint8_t i = 0; i < OVERSAMPLE; i++) sum += analogRead(A0);
  return (uint16_t)(sum / OVERSAMPLE);
}

void sampleTick(uint32_t now) {
  // 10 ms moving average
  uint16_t raw = readAdc();
  boxSum += raw;
  boxSum -= boxBuf[boxIdx];
  boxBuf[boxIdx] = raw;
  boxIdx = (boxIdx + 1) % BOX_LEN;
  level = (float)boxSum / BOX_LEN;

  // Dark (lo) and bright (hi) envelopes. They jump to new extremes at
  // once and only forget slowly, and only while waiting for a message,
  // so the threshold stays put during one.
  float decay = (phase == PHASE_IDLE) ? ENV_DECAY : 0.0f;
  if (level > hi) hi = level; else hi -= (hi - level) * decay;
  if (level < lo) lo = level; else lo += (level - lo) * decay;
  swing = hi - lo;
  thr = 0.5f * (hi + lo);

  // Need real contrast before anything counts as light
  if (signalPresent) {
    if (swing < minSwing * 0.7f) signalPresent = false;
  } else if (swing >= minSwing) {
    signalPresent = true;
  }

  // Threshold halfway between dark and bright, with hysteresis
  float hyst = swing * 0.12f;
  if (hyst < 3.0f) hyst = 3.0f;
  bool want = signalPresent && (lit ? (level > thr - hyst) : (level > thr + hyst));

  // Debounce. The edge time is when the change first appeared.
  if (want != lit) {
    if (!pending) {
      pending = true;
      pendCount = 0;
      pendSinceUs = now;
    }
    if (++pendCount >= DEBOUNCE_TICKS) {
      lit = want;
      pending = false;
      processEdge(lit, pendSinceUs);
    }
  } else {
    pending = false;
  }

  checkTimeouts(now);
}

// ================================================================
// Decoder
// ================================================================

void processEdge(bool rising, uint32_t t) {
  if (rising) {
    if (phase != PHASE_IDLE) onGap(t - lastFallUs);
    lastRiseUs = t;
  } else {
    onPulse(t - lastRiseUs);
    lastFallUs = t;
  }
}

// A light pulse just ended (falling edge)
void onPulse(uint32_t onUs) {
  bool syncLength = (onUs >= SYNC_MIN_US && onUs <= SYNC_MAX_US);

  if (phase == PHASE_IDLE) {
    if (syncLength) {
      syncOnUs = onUs;
      phase = PHASE_SYNC;
    }
  } else if (phase == PHASE_MESSAGE) {
    if (onUs >= 6UL * unitUs) {
      // Far longer than any dash: a new message is starting
      endMessage();
      if (syncLength) {
        syncOnUs = onUs;
        phase = PHASE_SYNC;
      } else {
        phase = PHASE_IDLE;
      }
    } else {
      addSymbol(correctedOn(onUs) < 2UL * unitUs ? '.' : '-');   // dot 1 unit, dash 3
    }
  }
}

// A dark gap just ended (rising edge)
void onGap(uint32_t offUs) {
  if (phase == PHASE_SYNC) {
    // The gap after the sync pulse should be a third of its length
    if (offUs * 6 >= syncOnUs && offUs * 2 <= syncOnUs) {
      uint32_t u = (syncOnUs + offUs) / 12;
      if (u >= UNIT_MIN_US && u <= UNIT_MAX_US) {
        unitUs = u;

        // on = 9 units + skew, off = 3 units - skew  ->  skew = (on - 3*off) / 4
        int32_t skew = ((int32_t)syncOnUs - 3 * (int32_t)offUs) / 4;
        if (skew > (int32_t)u) skew = (int32_t)u;
        if (skew < -(int32_t)u) skew = -(int32_t)u;
        biasUs = skew;

        symLen = 0;
        symOverflow = false;
        msgStarted = false;
        phase = PHASE_MESSAGE;
        return;
      }
    }
    phase = PHASE_IDLE;
    return;
  }

  if (phase == PHASE_MESSAGE) {
    uint32_t gap = correctedOff(offUs);
    if (gap * 2 >= unitUs * 3) flushLetter();        // 1.5 units or more: letter ended
    if (gap >= 4UL * unitUs && msgStarted) {         // 4 units or more: word gap
      Serial.println("W");
    }
  }
}

// Called every sample. Finishes letters and messages when the light
// stays dark, since no edge arrives to announce them.
void checkTimeouts(uint32_t now) {
  if (lit) {
    // Light stuck on (alignment mode): give up on the message
    if (phase == PHASE_MESSAGE && (uint32_t)(now - lastRiseUs) > 12UL * unitUs) {
      endMessage();
      phase = PHASE_IDLE;
    }
    return;
  }

  uint32_t offRaw = now - lastFallUs;

  if (phase == PHASE_SYNC) {
    if (offRaw * 2 > syncOnUs) phase = PHASE_IDLE;   // gap too long to be a sync
  } else if (phase == PHASE_MESSAGE) {
    uint32_t off = correctedOff(offRaw);
    if (off * 2 >= unitUs * 3) flushLetter();
    if (off >= 10UL * unitUs) {
      endMessage();
      phase = PHASE_IDLE;
    }
  }
}

// Remove the LDR's rise/fall skew from a measured duration
uint32_t correctedOn(uint32_t onUs) {
  int32_t v = (int32_t)onUs - biasUs;
  return v < 0 ? 0 : (uint32_t)v;
}

uint32_t correctedOff(uint32_t offUs) {
  int32_t v = (int32_t)offUs + biasUs;
  return v < 0 ? 0 : (uint32_t)v;
}

void addSymbol(char c) {
  if (symLen < 6) sym[symLen++] = c;
  else symOverflow = true;
}

void flushLetter() {
  if (symLen == 0) return;
  char c = symOverflow ? '?' : decodeSymbols();
  symLen = 0;
  symOverflow = false;
  emitChar(c);
}

void endMessage() {
  flushLetter();
  if (msgStarted) {
    Serial.println("E");
    msgStarted = false;
  }
}

char decodeSymbols() {
  sym[symLen] = '\0';
  for (uint8_t i = 0; i < 26; i++) if (strcmp(sym, LETTERS[i]) == 0) return (char)('A' + i);
  for (uint8_t i = 0; i < 10; i++) if (strcmp(sym, DIGITS[i]) == 0)  return (char)('0' + i);
  return '?';
}

void emitChar(char c) {
  if (!msgStarted) {
    Serial.printf("B,%lu\n", (unsigned long)(unitUs / 1000UL));
    msgStarted = true;
  }
  Serial.print("C,");
  Serial.println(c);
}

// ================================================================
// Commands from the dashboard
// ================================================================

void resetDetector() {
  phase = PHASE_IDLE;
  biasUs = 0;
  symLen = 0;
  symOverflow = false;
  msgStarted = false;
  lit = false;
  pending = false;
  signalPresent = false;
  hi = lo = thr = level;
  swing = 0;
}

void sendHello() {
  Serial.printf("H,VLC-RX,1,%d\n", (int)minSwing);
}

void pollCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdLen > 0) handleCommand();
      cmdLen = 0;
    } else if (cmdLen < sizeof(cmd) - 1) {
      cmd[cmdLen++] = c;
    }
  }
}

void handleCommand() {
  cmd[cmdLen] = '\0';
  switch (cmd[0]) {
    case 'R':
      resetDetector();
      break;
    case 'M': {
      int v = atoi(cmd + 1);
      if (v < 8) v = 8;
      if (v > 300) v = 300;
      minSwing = (float)v;
      break;
    }
    case '?':
      sendHello();
      break;
  }
}
