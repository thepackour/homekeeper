// 현관 우노: 부품을 읽고 움직이기만 한다. 판단은 Pi가 한다.
//
// 우노 -> Pi (9600, 한 줄씩): READY / BTN / IR:0x0C / DIST:25 (못 재면 DIST:-1)
// Pi -> 우노: LCD0:글자 / LCD1:글자 / BEEP:주파수,밀리초
//
// Pi가 LCD 명령을 보내기 전에는 LCD 둘째 줄에 센서 값을 보여 줘서 우노만으로 부품을 확인할 수 있다.
#include <Wire.h>

const uint8_t LCD_ADDRESS = 0x3F;
const uint8_t BUTTON_PIN = 2;
const uint8_t IR_PIN = 3;
const uint8_t TRIG_PIN = 8;
const uint8_t ECHO_PIN = 9;
const uint8_t BUZZER_PIN = 12;

const uint8_t LCD_RS = 0x01;
const uint8_t LCD_ENABLE = 0x04;
const uint8_t LCD_BACKLIGHT = 0x08;

const unsigned long DISTANCE_INTERVAL_MS = 300;
const unsigned long DEBOUNCE_MS = 50;
const unsigned int MAX_BEEP_MS = 2000;

// IR (NEC 방식) 수신 상태. 신호가 바뀔 때마다 인터럽트에서 처리한다.
volatile unsigned long irLastEdge = 0;
volatile uint8_t irState = 0;
volatile uint8_t irBitCount = 0;
volatile uint32_t irBits = 0;
volatile uint32_t irFrame = 0;
volatile bool irFrameReady = false;

char inputLine[32];
uint8_t inputLength = 0;
bool piConnected = false;

int lastDistance = -1;
unsigned int buttonCount = 0;
uint8_t lastIrCode = 0;
unsigned long lastDistanceTime = 0;
bool lastButtonReading = HIGH;
bool buttonState = HIGH;
unsigned long lastButtonChange = 0;

void expanderWrite(uint8_t value) {
  Wire.beginTransmission(LCD_ADDRESS);
  Wire.write(value | LCD_BACKLIGHT);
  Wire.endTransmission();
}

void lcdNibble(uint8_t value) {
  expanderWrite(value);
  expanderWrite(value | LCD_ENABLE);
  delayMicroseconds(500);
  expanderWrite(value & ~LCD_ENABLE);
  delayMicroseconds(100);
}

void lcdSend(uint8_t value, uint8_t mode) {
  lcdNibble(mode | (value & 0xF0));
  lcdNibble(mode | ((value << 4) & 0xF0));
}

void lcdInit() {
  Wire.begin();
  delay(50);
  lcdNibble(0x30);
  delay(5);
  lcdNibble(0x30);
  delay(1);
  lcdNibble(0x30);
  delay(1);
  lcdNibble(0x20);
  delay(1);
  lcdSend(0x28, 0);  // 4비트, 2줄
  lcdSend(0x0C, 0);  // 화면 켜기, 커서 끄기
  lcdSend(0x06, 0);  // 글자를 쓰면 오른쪽으로 이동
  lcdSend(0x01, 0);  // 화면 지우기
  delay(2);
}

void lcdLine(uint8_t line, const char *text) {
  lcdSend(0x80 | (line ? 0x40 : 0x00), 0);
  uint8_t i = 0;
  for (; i < 16 && text[i]; i++) {
    lcdSend(text[i], LCD_RS);
  }
  for (; i < 16; i++) {
    lcdSend(' ', LCD_RS);
  }
}

void onIrEdge() {
  unsigned long now = micros();
  unsigned long width = now - irLastEdge;
  irLastEdge = now;
  bool level = digitalRead(IR_PIN);

  if (irState == 0) {
    if (level == HIGH && width > 7000 && width < 11000) {
      irState = 1;  // 시작 신호(약 9ms) 끝
    }
  } else if (irState == 1) {
    if (level == LOW) {
      if (width > 3500 && width < 5500) {
        irState = 2;  // 시작 신호의 쉬는 구간(약 4.5ms) 끝. 데이터 시작
        irBitCount = 0;
        irBits = 0;
      } else {
        irState = 0;  // 버튼을 누르고 있을 때 오는 반복 신호 등
      }
    }
  } else if (level == LOW) {
    if (width > 300 && width < 800) {
      irBitCount++;
    } else if (width > 1200 && width < 2200) {
      irBits |= 1UL << irBitCount;
      irBitCount++;
    } else {
      irState = 0;
      return;
    }
    if (irBitCount == 32) {
      irFrame = irBits;
      irFrameReady = true;
      irState = 0;
    }
  }
}

void checkIr() {
  if (!irFrameReady) {
    return;
  }
  noInterrupts();
  uint32_t frame = irFrame;
  irFrameReady = false;
  interrupts();

  uint8_t command = (frame >> 16) & 0xFF;
  uint8_t inverted = (frame >> 24) & 0xFF;
  if ((command ^ inverted) != 0xFF) {
    return;
  }
  lastIrCode = command;
  Serial.print(F("IR:0x"));
  if (command < 0x10) {
    Serial.print('0');
  }
  Serial.println(command, HEX);
}

void checkButton() {
  bool reading = digitalRead(BUTTON_PIN);
  if (reading != lastButtonReading) {
    lastButtonChange = millis();
    lastButtonReading = reading;
  }
  if (millis() - lastButtonChange > DEBOUNCE_MS && reading != buttonState) {
    buttonState = reading;
    if (buttonState == LOW) {
      buttonCount++;
      Serial.println(F("BTN"));
    }
  }
}

int measureCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 25000UL);
  return duration == 0 ? -1 : (int)(duration / 58);
}

void showLocalStatus() {
  char text[17];
  if (lastDistance < 0) {
    snprintf(text, sizeof(text), "D:-- B:%u IR:%02X", buttonCount, lastIrCode);
  } else {
    snprintf(text, sizeof(text), "D:%d B:%u IR:%02X", lastDistance, buttonCount, lastIrCode);
  }
  lcdLine(1, text);
}

void checkDistance() {
  if (millis() - lastDistanceTime < DISTANCE_INTERVAL_MS) {
    return;
  }
  lastDistanceTime = millis();
  lastDistance = measureCm();
  Serial.print(F("DIST:"));
  Serial.println(lastDistance);
  if (!piConnected) {
    showLocalStatus();
  }
}

// IR 리모컨을 쓰는 아두이노 A는 tone()을 쓰지 않기로 해서 digitalWrite로 소리를 만든다.
// 소리가 나는 동안은 다른 일을 멈추므로 길이를 제한한다. IR 수신은 인터럽트라 계속 동작한다.
void beep(unsigned int frequency, unsigned int duration) {
  if (frequency < 31) {
    return;
  }
  duration = min(duration, MAX_BEEP_MS);
  unsigned int halfPeriod = 500000UL / frequency;
  unsigned long cycles = (unsigned long)frequency * duration / 1000UL;
  for (unsigned long i = 0; i < cycles; i++) {
    digitalWrite(BUZZER_PIN, HIGH);
    delayMicroseconds(halfPeriod);
    digitalWrite(BUZZER_PIN, LOW);
    delayMicroseconds(halfPeriod);
  }
}

void handleCommand(char *line) {
  if (strncmp(line, "LCD0:", 5) == 0) {
    piConnected = true;
    lcdLine(0, line + 5);
  } else if (strncmp(line, "LCD1:", 5) == 0) {
    piConnected = true;
    lcdLine(1, line + 5);
  } else if (strncmp(line, "BEEP:", 5) == 0) {
    unsigned int frequency = 0;
    unsigned int duration = 0;
    if (sscanf(line + 5, "%u,%u", &frequency, &duration) == 2) {
      beep(frequency, duration);
    }
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      inputLine[inputLength] = '\0';
      handleCommand(inputLine);
      inputLength = 0;
    } else if (c != '\r' && inputLength < sizeof(inputLine) - 1) {
      inputLine[inputLength++] = c;
    }
  }
}

void setup() {
  Serial.begin(9600);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(IR_PIN, INPUT_PULLUP);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);

  lcdInit();
  lcdLine(0, "HOMEKEEPER");

  attachInterrupt(digitalPinToInterrupt(IR_PIN), onIrEdge, CHANGE);

  const unsigned int notes[] = {1047, 1319, 1568};
  for (uint8_t i = 0; i < 3; i++) {
    beep(notes[i], 150);
    delay(50);
  }
  Serial.println(F("READY"));
}

void loop() {
  readSerial();
  checkButton();
  checkIr();
  checkDistance();
}
