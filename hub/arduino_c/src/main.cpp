// 홈키파 아두이노 C: 도트매트릭스(MAX7219), 경보 LED, 부저
// 매트릭스 헤더 2번 5V, 6번 GND, 19번 DIN→D11, 24번 CS→D10, 23번 CLK→D13
// 초록 LED D5, 빨간 LED D6 (220Ω), 부저 D7
// Pi → 아두이노: S0 정상, S1 주의, S2 경고, S3 경보, T 테스트
#include <Arduino.h>
#define MAP 8              // 찾기 프로그램에서 켜진 번호 (8 또는 5)
#if MAP == 8
#define PIN_DIN 11
#define PIN_CS 10
#define PIN_CLK 13
#else
#define PIN_DIN 10
#define PIN_CS 13
#define PIN_CLK 11
#endif
#define PIN_GREEN 5
#define PIN_RED 6
#define PIN_BUZZ 7
#define PASSIVE_BUZZER 0   // 수동 부저면 1
#define MX_CHAIN 4         // 칩이 줄줄이 몇 번째든 같은 그림을 받게 4칸 분량 전송

const byte ICON_OK[8]   = {0x00, 0x01, 0x03, 0x86, 0xCC, 0x78, 0x30, 0x00};
const byte ICON_Q[8]    = {0x3C, 0x66, 0x06, 0x0C, 0x18, 0x00, 0x18, 0x00};
const byte ICON_EXCL[8] = {0x18, 0x18, 0x18, 0x18, 0x18, 0x00, 0x18, 0x00};
const byte ICON_X[8]    = {0xC3, 0x66, 0x3C, 0x18, 0x18, 0x3C, 0x66, 0xC3};

int level = 0;
bool blinkOn = false, testing = false;
unsigned long lastBlink = 0, lastBeep = 0, testT = 0;
int testStep = 0;
String line = "";

void mxByte(byte b) {
  for (int i = 7; i >= 0; i--) {
    digitalWrite(PIN_CLK, LOW);
    digitalWrite(PIN_DIN, (b >> i) & 1);
    digitalWrite(PIN_CLK, HIGH);
  }
  digitalWrite(PIN_CLK, LOW);
}
void mxSend(byte reg, byte val) {
  digitalWrite(PIN_CS, LOW);
  for (int d = 0; d < MX_CHAIN; d++) { mxByte(reg); mxByte(val); }
  digitalWrite(PIN_CS, HIGH);
}
void mxInit() {
  pinMode(PIN_DIN, OUTPUT); pinMode(PIN_CLK, OUTPUT); pinMode(PIN_CS, OUTPUT);
  digitalWrite(PIN_CS, HIGH); digitalWrite(PIN_CLK, LOW);
  mxSend(0x0C, 1);                  // 켜기
  mxSend(0x0F, 1); delay(1000);     // 1초 전체 점등 (살아 있는지 확인)
  mxSend(0x0F, 0);
  mxSend(0x09, 0);                  // 숫자 해석 끄기
  mxSend(0x0B, 7);                  // 8줄 사용
  mxSend(0x0A, 6);                  // 밝기
}
void showIcon(const byte *icon) { for (int r = 0; r < 8; r++) mxSend(r + 1, icon[r]); }
void clearAll() { for (int r = 0; r < 8; r++) mxSend(r + 1, 0); }

void buzz(bool on) {
#if PASSIVE_BUZZER
  if (on) tone(PIN_BUZZ, 2000); else noTone(PIN_BUZZ);
#else
  digitalWrite(PIN_BUZZ, on ? HIGH : LOW);
#endif
}

void setLevel(int lv) {
  level = constrain(lv, 0, 3);
  blinkOn = true; lastBlink = millis(); lastBeep = 0;
  buzz(false);
  digitalWrite(PIN_GREEN, level <= 1 ? HIGH : LOW);
  digitalWrite(PIN_RED, level >= 2 ? HIGH : LOW);
  const byte *icons[] = {ICON_OK, ICON_Q, ICON_EXCL, ICON_X};
  showIcon(icons[level]);
}

void handle(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;
  if (cmd[0] == 'S' && cmd.length() >= 2) {
    testing = false; setLevel(cmd[1] - '0');
    Serial.print("OK S"); Serial.println(level);
  } else if (cmd[0] == 'T') {
    testing = true; testStep = 0; testT = 0;
    Serial.println("OK T");
  }
}

void setup() {
  pinMode(PIN_GREEN, OUTPUT); pinMode(PIN_RED, OUTPUT); pinMode(PIN_BUZZ, OUTPUT);
  Serial.begin(9600);
  delay(200);
  mxInit();
  setLevel(0);
  Serial.println("READY C v3");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { handle(line); line = ""; }
    else if (c != '\r' && line.length() < 16) line += c;
  }
  unsigned long t = millis();
  if (testing && t - testT >= 2000) {
    testT = t;
    setLevel(testStep <= 3 ? testStep : 0);
    if (++testStep > 4) testing = false;
  }
  if (level == 2) {
    if (t - lastBlink >= 500) { lastBlink = t; blinkOn = !blinkOn; digitalWrite(PIN_RED, blinkOn); }
    if (t - lastBeep >= 2000) { lastBeep = t; buzz(true); }
    if (t - lastBeep >= 150) buzz(false);
  } else if (level == 3) {
    if (t - lastBlink >= 150) {
      lastBlink = t; blinkOn = !blinkOn;
      digitalWrite(PIN_RED, blinkOn);
      if (blinkOn) showIcon(ICON_X); else clearAll();
      buzz(blinkOn);
    }
  }
}
