// ================================================================
// VLC TRANSMITTER: ESP32 firmware for the Streamlit dashboard
// ================================================================
// Serial protocol (115200 baud, sent by app.py):
//
//   "@<ms>\n"   set the Morse time unit, 20-500 ms. The dashboard sends
//               this before every message, so the speed slider works.
//   "["         alignment mode: hold the LED on
//   "]"         alignment mode off: LED off
//   A-Z 0-9     transmitted as Morse
//   space or /  word gap
//   anything else is ignored
//
// Timing matches the dashboard exactly (in units):
//   dot 1 on | dash 3 on | gap between symbols 1 off
//   gap between letters 2 off | gap between words 6 off
//
// Every message starts with a sync pulse: 9 units on, 3 units off.
// The receiver measures it to learn the speed, so the two ends never
// need to be set to the same time unit by hand. A sync is sent
// whenever the link has been idle for more than 8 units.
//
// There is no trailing gap after the last letter, so the physical
// pulse train has the same length as the dashboard's waveform.
// ================================================================

#include <Arduino.h>

// ---------------- hardware ----------------
const uint8_t  LED_PIN   = 4;        // GPIO4 -> BJT base (through a resistor)
const uint32_t BAUD_RATE = 115200;   // must match the dashboard

// ---------------- timing ----------------
const uint16_t UNIT_MS_DEFAULT = 100;
const uint16_t UNIT_MS_MIN     = 20;
const uint16_t UNIT_MS_MAX     = 500;

const uint8_t SYNC_ON_UNITS   = 9;   // long pulse that opens a message
const uint8_t SYNC_OFF_UNITS  = 3;
const uint8_t SYNC_IDLE_UNITS = 8;   // idle longer than this -> new message

// ---------------- Morse tables ----------------
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
uint16_t unitMs          = UNIT_MS_DEFAULT;
bool     calibrating     = false;

bool     haveLastLetter  = false;  // a letter has been sent before
bool     wordBreakNext   = false;  // a space arrived after the last letter
uint32_t lastLetterEndMs = 0;      // when the last letter finished

bool     readingUnit     = false;  // inside an "@<ms>" command
uint32_t unitAccum       = 0;

// ---------------- prototypes ----------------
void handleByte(char c);
void beginLetter();
void sendSync();
void sendCode(const char* code);

// ================================================================

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);      // start dark

  // Messages are sent in one burst but played slowly, so the receive
  // buffer must hold a whole message (the default is only 256 bytes).
  Serial.setRxBufferSize(2048);
  Serial.begin(BAUD_RATE);
}

void loop() {
  while (Serial.available() > 0) {
    handleByte((char)Serial.read());
  }
}

// ================================================================

void handleByte(char c) {
  // ---- "@<ms>\n": speed command ----
  if (readingUnit) {
    if (c >= '0' && c <= '9') {
      if (unitAccum < 10000) unitAccum = unitAccum * 10 + (c - '0');
      return;
    }
    readingUnit = false;
    if (unitAccum >= UNIT_MS_MIN && unitAccum <= UNIT_MS_MAX) {
      unitMs = (uint16_t)unitAccum;
    }
    if (c == '\n' || c == '\r') return;   // terminator, nothing more to do
    // otherwise fall through and treat c as a normal character
  }

  if (c == '@') {
    readingUnit = true;
    unitAccum = 0;
    return;
  }

  c = (char)toupper((unsigned char)c);

  // ---- alignment mode ----
  if (c == '[') {
    calibrating = true;
    digitalWrite(LED_PIN, HIGH);
    return;
  }
  if (c == ']') {
    calibrating = false;
    digitalWrite(LED_PIN, LOW);
    return;
  }
  if (calibrating) return;   // keep the LED on; ignore message data

  // ---- message data ----
  const char* code = nullptr;
  if (c >= 'A' && c <= 'Z')      code = LETTERS[c - 'A'];
  else if (c >= '0' && c <= '9') code = DIGITS[c - '0'];

  if (code != nullptr) {
    beginLetter();
    sendCode(code);
    haveLastLetter  = true;
    wordBreakNext   = false;
    lastLetterEndMs = millis();
  } else if (c == ' ' || c == '/') {
    if (haveLastLetter) wordBreakNext = true;
  }
  // everything else (newlines, punctuation) is ignored
}

// Called before every letter. Opens a new message with a sync pulse
// after a long idle; otherwise waits out the gap since the previous
// letter: 2 units, or 6 after a space. The gap is measured from when
// that letter ended, so data that arrives late never gets extra delay.
void beginLetter() {
  uint32_t idle = millis() - lastLetterEndMs;
  bool freshMessage =
      !haveLastLetter || idle > (uint32_t)unitMs * SYNC_IDLE_UNITS;

  if (freshMessage) {
    sendSync();
    return;
  }

  uint32_t gap = (uint32_t)unitMs * (wordBreakNext ? 6 : 2);
  if (idle < gap) delay(gap - idle);
}

// Sync: 9 units on, 3 units off. The receiver recovers the time unit
// from (on + off) / 12, which cancels any edge-detection offset.
void sendSync() {
  digitalWrite(LED_PIN, HIGH);
  delay((uint32_t)unitMs * SYNC_ON_UNITS);
  digitalWrite(LED_PIN, LOW);
  delay((uint32_t)unitMs * SYNC_OFF_UNITS);
}

// Flash one letter: dot = 1 unit on, dash = 3 units on,
// 1 unit off between symbols (none after the last one).
void sendCode(const char* code) {
  for (size_t i = 0; code[i] != '\0'; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(code[i] == '.' ? unitMs : (uint32_t)unitMs * 3);
    digitalWrite(LED_PIN, LOW);

    if (code[i + 1] != '\0') delay(unitMs);
  }
}
