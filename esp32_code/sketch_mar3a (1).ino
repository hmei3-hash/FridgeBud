#define LDR_PIN 5
#define BUTTON_PIN 0
#define POT_PIN 2

#define TRIG_PIN 9
#define ECHO_PIN 10

#define TIMEOUT 30000

void setup() {
  Serial.begin(115200);


  pinMode(POT_PIN, INPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  digitalWrite(TRIG_PIN, LOW);

  delay(1000);
}

float readDistanceCM() {

  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);

  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, TIMEOUT);

  if (duration == 0) return -1;

  return duration * 0.0343 / 2;
}

void loop() {

  int potValue = analogRead(POT_PIN);
  bool buttonPressed = (digitalRead(BUTTON_PIN) == LOW);

  float distance = readDistanceCM();

  Serial.print(" | POT:");
  Serial.print(potValue);

  Serial.print(" | BTN:");
  Serial.print(buttonPressed);

  Serial.print(" | DIST:");
  if (distance < 0) Serial.print("OutOfRange");
  else Serial.print(distance);

  Serial.println();

  delay(200);
}