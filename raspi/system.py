import serial
import json
import threading
import queue
import time
import cv2
import RPi.GPIO as GPIO

# =============================
# ===== LCD ??(????)=====
# =============================

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

RS = 17
EN = 27
D4 = 5
D5 = 6
D6 = 13
D7 = 19

pins = [RS, EN, D4, D5, D6, D7]

for pin in pins:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

class LCD:
    def __init__(self):
        self.init_display()

    def pulse_en(self):
        GPIO.output(EN, GPIO.HIGH)
        time.sleep(0.0005)
        GPIO.output(EN, GPIO.LOW)
        time.sleep(0.0005)

    def send_nibble(self, nibble):
        GPIO.output(D4, nibble & 0x01)
        GPIO.output(D5, (nibble >> 1) & 0x01)
        GPIO.output(D6, (nibble >> 2) & 0x01)
        GPIO.output(D7, (nibble >> 3) & 0x01)
        self.pulse_en()

    def send_byte(self, byte, mode=0):
        GPIO.output(RS, mode)
        self.send_nibble(byte >> 4)
        self.send_nibble(byte & 0x0F)
        time.sleep(0.001)

    def init_display(self):
        time.sleep(0.1)
        self.send_nibble(0x03); time.sleep(0.005)
        self.send_nibble(0x03); time.sleep(0.005)
        self.send_nibble(0x03); time.sleep(0.005)
        self.send_nibble(0x02); time.sleep(0.005)

        self.send_byte(0x28, 0)
        self.send_byte(0x0C, 0)
        self.send_byte(0x06, 0)
        self.send_byte(0x01, 0)
        time.sleep(0.005)

    def write_string(self, text):
        for char in text[:16]:
            self.send_byte(ord(char), 1)

    def goto(self, line, col=0):
        addr = 0x80 + col if line == 0 else 0xC0 + col
        self.send_byte(addr, 0)

    def clear(self):
        self.send_byte(0x01, 0)
        time.sleep(0.005)

lcd = LCD()

# =============================
# UART ??
# =============================

PORT = "/dev/serial0"
BAUD = 115200
data_queue = queue.Queue()

# =============================
# ???
# =============================

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

# =============================
# ??
# =============================

last_photo_time = 0
PHOTO_COOLDOWN = 2

def take_photo():
    global last_photo_time
    if time.time() - last_photo_time < PHOTO_COOLDOWN:
        return

    ret, frame = cap.read()
    if ret:
        filename = f"photo_{int(time.time())}.jpg"
        cv2.imwrite(filename, frame)
        lcd.clear()
        lcd.goto(0,0)
        lcd.write_string("Photo Saved")
        last_photo_time = time.time()

# =============================
# ????
# =============================

def uart_listener():
    ser = serial.Serial(PORT, BAUD, timeout=1)
    while True:
        try:
            line = ser.readline().decode().strip()
            if not line:
                continue
            data = json.loads(line)
            data_queue.put(data)
        except:
            continue

# =============================
# ?????
# =============================

def logic_loop():
    NEAR_THRESHOLD = 20
    is_near = False

    while True:
        if not data_queue.empty():
            data = data_queue.get()

            dist = data.get("dist")
            b1 = data.get("b1")

            if dist and dist > 0:
                if dist < NEAR_THRESHOLD and not is_near:
                    is_near = True
                    lcd.clear()
                    lcd.goto(0,0)
                    lcd.write_string("hi lol")

                elif dist >= NEAR_THRESHOLD and is_near:
                    is_near = False
                    lcd.clear()

            if b1 == 1:
                take_photo()

        time.sleep(0.01)

# =============================
# ????
# =============================

t1 = threading.Thread(target=uart_listener, daemon=True)
t2 = threading.Thread(target=logic_loop, daemon=True)

t1.start()
t2.start()

print("System Running...")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    lcd.clear()
    GPIO.cleanup()
    cap.release()
