#define POT_PIN 6
#define BTN1_PIN 5
#define BTN2_PIN 2

//TODO：连接txrx，共地
#define TX_PIN 21
#define RX_PIN 20
#define TRIG_PIN 1
#define ECHO_PIN 0

#define TIMEOUT 30000   // 30ms 超时 (约5米)

HardwareSerial MySerial(0);

// ===== POT 滤波参数 =====
float filteredPot = 0;
float alphaPot = 0.15;
int lastSentPot = -1;
int potThreshold = 15;

// ===== 超声波滤波参数 =====
float filteredDist = 0;
float alphaDist = 0.3;
float lastSentDist = -1;
float distThreshold = 1.5;   // 1.5cm 才发送

// ===== 按钮防抖 =====
unsigned long lastPress1 = 0;
unsigned long lastPress2 = 0;
unsigned long lastPress3 = 0;
const int debounceDelay = 200;

bool checkButton(int pin, unsigned long &lastPress) {
    if (digitalRead(pin) == LOW) {
        if (millis() - lastPress > debounceDelay) {
            lastPress = millis();
            return true;
        }
    }
    return false;
}

void setup() {
    Serial.begin(115200);
    MySerial.begin(115200, SERIAL_8N1, RX_PIN, TX_PIN);

    pinMode(BTN1_PIN, INPUT_PULLUP);
    pinMode(BTN2_PIN, INPUT_PULLUP);

    analogReadResolution(12);
    filteredPot = analogRead(POT_PIN);

    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    digitalWrite(TRIG_PIN, LOW);

    delay(1000);
}

// ===== 超声波读取 =====
float readDistanceCM() {
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);

    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);

    long duration = pulseIn(ECHO_PIN, HIGH, TIMEOUT);

    if (duration == 0) return -1;

    return duration * 0.0343 / 2.0;
}

void loop() {

    // ===== POT 滤波 =====
    int rawPot = analogRead(POT_PIN);
    filteredPot = alphaPot * rawPot + (1 - alphaPot) * filteredPot;
    int potInt = (int)filteredPot;

    bool potChanged = false;
    if (abs(potInt - lastSentPot) > potThreshold) {
        potChanged = true;
        lastSentPot = potInt;
    }

    // ===== 超声波读取 + 滤波 =====
    float rawDist = readDistanceCM();

    bool distChanged = false;

    if (rawDist > 0) {   // 有效数据才滤波
        filteredDist = alphaDist * rawDist + (1 - alphaDist) * filteredDist;

        if (abs(filteredDist - lastSentDist) > distThreshold) {
            distChanged = true;
            lastSentDist = filteredDist;
        }
    }

    // ===== 按钮 =====
    int b1 = checkButton(BTN1_PIN, lastPress1) ? 1 : 0;
    int b2 = checkButton(BTN2_PIN, lastPress2) ? 1 : 0;

    // ===== 变化才发送 =====
    if (potChanged || distChanged || b1 || b2) {

        String json = "{";
        json += "\"pot\":";
        json += potInt;
        json += ",\"b1\":";
        json += b1;
        json += ",\"b2\":";
        json += b2;
        json += ",\"dist\":";
        json += filteredDist;
        json += "}";

        MySerial.println(json);
        Serial.println(json);
    }

    delay(20);
}