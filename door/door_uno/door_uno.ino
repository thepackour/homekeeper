// 현관 우노: 부품을 읽고 움직이기만 한다. 판단은 Pi가 한다.
//
// 우노 -> Pi (9600, 한 줄씩): READY / BTN / IR:0x0C / DIST:25 (못 재면 DIST:-1) / CARD:A1B2C3D4
// Pi -> 우노: LCD0:글자 / LCD1:글자 / BEEP:주파수,밀리초 / DOOR:OPEN / DOOR:LOCK
//
// Pi가 LCD 명령을 보내기 전에는 LCD에 센서 값과 카드 번호를 보여 줘서 우노만으로 부품을 확인할 수 있다.
// 이때 버튼을 누르면 서보가 열림과 잠김을 번갈아 움직인다 (각도 맞추기용).
// 카드 리더 RC522는 라이브러리 관리자에서 "MFRC522" (GithubCommunity)를 설치해야 컴파일된다.
// 서보는 Arduino IDE에 들어 있는 Servo 라이브러리를 쓴다 (따로 설치할 것 없음).
#include <SPI.h>
#include <Wire.h>
#include <MFRC522.h>
#include <Servo.h>

const uint8_t LCD_ADDRESS = 0x3F;
const uint8_t BUTTON_PIN = 2;
const uint8_t IR_PIN = 3;
const uint8_t TRIG_PIN = 8;
const uint8_t ECHO_PIN = 9;
const uint8_t BUZZER_PIN = 6;      // D12는 카드 리더(MISO)가 써서 D6으로 옮김
const uint8_t RC522_SS_PIN = 10;   // RC522 SDA. SPI는 D11(MOSI), D12(MISO), D13(SCK) 고정
const uint8_t RC522_RST_PIN = 7;
const uint8_t SERVO_PIN = 5;       // SG90 주황(신호) 선

// 서보 각도. 문에 붙인 뒤 버튼으로 움직여 보고 맞게 고친다 (0~180).
const uint8_t LOCK_ANGLE = 0;      // 잠김: 걸쇠가 문을 막는 위치
const uint8_t OPEN_ANGLE = 90;     // 열림: 걸쇠가 비켜난 위치
const unsigned long SERVO_MOVE_MS = 700;  // 다 돌 때까지 기다린 뒤 신호를 끊는다

const uint8_t LCD_RS = 0x01;
const uint8_t LCD_ENABLE = 0x04;
const uint8_t LCD_BACKLIGHT = 0x08;

const unsigned long DISTANCE_INTERVAL_MS = 300;
const unsigned long DEBOUNCE_MS = 50;
const unsigned int MAX_BEEP_MS = 2000;
const unsigned long CARD_POLL_MS = 150;   // 카드가 없을 때 한 번 확인에 약 25ms 걸려서 가끔만 본다
const unsigned long SAME_CARD_MS = 1500;  // 같은 카드가 바로 다시 읽히면 무시

// IR (NEC 방식) 수신 상태. 신호가 바뀔 때마다 인터럽트에서 처리한다.
volatile unsigned long irLastEdge = 0;
volatile uint8_t irState = 0;
volatile uint8_t irBitCount = 0;
volatile uint32_t irBits = 0;
volatile uint32_t irFrame = 0;
volatile bool irFrameReady = false;

MFRC522 cardReader(RC522_SS_PIN, RC522_RST_PIN);
Servo doorServo;
bool doorOpen = false;
bool servoMoving = false;
unsigned long servoStartTime = 0;
char lastCard[21] = "";
unsigned long lastCardTime = 0;
unsigned long lastCardPoll = 0;

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

void checkCard() {
  if (millis() - lastCardPoll < CARD_POLL_MS) {
    return;
  }
  lastCardPoll = millis();
  if (!cardReader.PICC_IsNewCardPresent() || !cardReader.PICC_ReadCardSerial()) {
    return;
  }

  // 카드 번호(UID)를 16진수 글자로 만든다. 보통 4바이트라 8글자.
  char uid[21];
  uint8_t size = min(cardReader.uid.size, (byte)10);
  for (uint8_t i = 0; i < size; i++) {
    snprintf(uid + i * 2, 3, "%02X", cardReader.uid.uidByte[i]);
  }
  uid[size * 2] = '\0';
  cardReader.PICC_HaltA();  // 카드를 대고 있어도 다시 읽히지 않게 재운다
  cardReader.PCD_StopCrypto1();

  bool repeated = strcmp(uid, lastCard) == 0 && millis() - lastCardTime < SAME_CARD_MS;
  lastCardTime = millis();
  if (repeated) {
    return;
  }
  strcpy(lastCard, uid);
  Serial.print(F("CARD:"));
  Serial.println(uid);
  if (!piConnected) {
    char text[17];
    snprintf(text, sizeof(text), "CARD:%s", uid);
    lcdLine(0, text);
  }
}

// 서보를 움직인다. 각도를 먼저 정하고 attach해야 켜질 때 엉뚱한 곳(90도)으로 튀지 않는다.
void setDoor(bool open) {
  doorOpen = open;
  doorServo.write(open ? OPEN_ANGLE : LOCK_ANGLE);
  if (!doorServo.attached()) {
    doorServo.attach(SERVO_PIN);
  }
  servoMoving = true;
  servoStartTime = millis();
}

// 다 돌았으면 신호를 끊는다. 멈춰 있는 동안 떨리거나 윙 소리가 나지 않고 전류도 덜 쓴다.
// SG90은 기어가 빡빡해서 신호를 끊어도 걸쇠 정도는 그 자리에 머문다.
void checkServo() {
  if (servoMoving && millis() - servoStartTime >= SERVO_MOVE_MS) {
    doorServo.detach();
    servoMoving = false;
  }
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
      if (!piConnected) {  // Pi 없이 우노만 켰을 때 서보 확인
        setDoor(!doorOpen);
        lcdLine(0, doorOpen ? "SERVO OPEN" : "SERVO LOCK");
      }
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
  } else if (strcmp(line, "DOOR:OPEN") == 0) {
    piConnected = true;
    setDoor(true);
  } else if (strcmp(line, "DOOR:LOCK") == 0) {
    piConnected = true;
    setDoor(false);
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

  SPI.begin();
  cardReader.PCD_Init();
  // 칩 버전을 읽어 배선을 확인한다. 0x00이나 0xFF면 선이 잘못된 것.
  byte version = cardReader.PCD_ReadRegister(MFRC522::VersionReg);
  char text[17];
  if (version == 0x00 || version == 0xFF) {
    snprintf(text, sizeof(text), "RC522 NOT FOUND");
  } else {
    snprintf(text, sizeof(text), "RC522 OK %02X", version);
  }
  lcdLine(0, text);
  Serial.print(F("RC522:0x"));
  if (version < 0x10) {
    Serial.print('0');
  }
  Serial.println(version, HEX);

  attachInterrupt(digitalPinToInterrupt(IR_PIN), onIrEdge, CHANGE);
  setDoor(false);  // 켜지면 잠근다 (우노가 다시 시작돼도 문이 열린 채로 남지 않게)

  const unsigned int notes[] = {1047, 1319, 1568};
  for (uint8_t i = 0; i < 3; i++) {
    beep(notes[i], 150);
    delay(50);
  }
  Serial.println(F("READY"));
}

void loop() {
  readSerial();
  checkServo();
  checkButton();
  checkIr();
  checkCard();
  checkDistance();
}
