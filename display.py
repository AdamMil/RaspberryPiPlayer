import board
import digitalio
from PIL import Image, ImageDraw, ImageFont
from RPi import GPIO
from adafruit_rgb_display import st7789

class Display:
    A = 5
    B = 6
    U = 17
    D = 22
    L = 27
    R = 23
    C = 4
    BACKLIGHT = 26

    Black = (0,0,0)
    Gray = (128,128,128)
    White = (255,255,255)

    def __init__(self, onpress=None):
        self.display = st7789.ST7789(
            board.SPI(), height=240, y_offset=80, rotation=180, baudrate=24000000,
            cs=digitalio.DigitalInOut(board.CE0), dc=digitalio.DigitalInOut(board.D25), rst=digitalio.DigitalInOut(board.D24))
        self.width = self.display.width
        self.height = self.display.height
        self.frame = Image.new("RGB", (self.width, self.height))
        self.draw = ImageDraw.Draw(self.frame)
        self.font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
        self.draw.font = self.font
        GPIO.setmode(GPIO.BCM)
        for b in [Display.A, Display.B, Display.U, Display.D, Display.L, Display.R, Display.C]:
            GPIO.setup(b, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            if onpress: GPIO.add_event_detect(b, GPIO.FALLING, callback=onpress, bouncetime=200)
        GPIO.setup(Display.BACKLIGHT, GPIO.OUT)
        self.power(False)
        self.flip()

    def center(self, text, fill=None, y=None, font=None):
        if font is None: font = self.font
        (w,h) = self.draw.textsize(text, font)
        if y is None: y = (self.height-h) // 2
        x = (self.width-w) // 2
        if x < 0: x = 0
        self.draw.text((x,y), text, fill, font)
        return (y,h)
        
    def cleanup(self):
        self.clear()
        self.flip()
        self.power(False)
        GPIO.cleanup()

    def clear(self, color = (0,0,0)): self.draw.rectangle((0, 0, self.width, self.height), outline=0, fill=color)
    def flip(self): self.display.image(self.frame)
    def power(self, on): GPIO.output(Display.BACKLIGHT, GPIO.HIGH if on else GPIO.LOW)
    def rect(self, x, y, width, height, color): self.draw.rectangle((x, y, x+width, y+height), outline=0, fill=color)
    def text(self, x, y, text, fill=None, font=None): self.draw.text((x,y), text, fill, font)
    def textsize(self, text, font=None): return self.draw.textsize(text, self.font if font is None else font)
