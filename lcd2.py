import RPi.GPIO as GPIO
import time

# ?? BCM ??(Pi5 ??)
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# GPIO ??(BCM??)
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

        # ?????
        self.send_nibble(0x03)
        time.sleep(0.005)
        self.send_nibble(0x03)
        time.sleep(0.005)
        self.send_nibble(0x03)
        time.sleep(0.005)
        self.send_nibble(0x02)
        time.sleep(0.005)
        
        self.send_byte(0x28, 0)  # 4bit, 2?
        self.send_byte(0x0C, 0)  # ???,???
        self.send_byte(0x06, 0)  # ????
        self.send_byte(0x01, 0)  # ??
        time.sleep(0.005)
    
    def write_char(self, char):
        self.send_byte(ord(char), 1)
    
    def write_string(self, text):
        for char in text[:16]:
            self.write_char(char)
    
    def goto(self, line, col=0):
        if line == 0:
            addr = 0x80 + col
        else:
            addr = 0xC0 + col
        self.send_byte(addr, 0)
    
    def clear(self):
        self.send_byte(0x01, 0)
        time.sleep(0.005)

lcd = LCD()

lcd.goto(0, 0)
lcd.write_string("Raspi 5 LCD")
lcd.goto(1, 0)
lcd.write_string("Ready")

time.sleep(2)

try:
    while True:
        text = input("Input: ")
        lcd.clear()
        lcd.goto(0, 0)
        lcd.write_string(text[:16])
        if len(text) > 16:
            lcd.goto(1, 0)
            lcd.write_string(text[16:32])
except KeyboardInterrupt:
    lcd.clear()
    GPIO.cleanup()
