import pygame
import os
import cv2
import torch
from PIL import Image
import threading
import queue
import numpy as np

# ===========================
# 初始化 Pygame
# ===========================
pygame.init()
screen = pygame.display.set_mode((800,600))
pygame.display.set_caption("FridgeBud Food + CV Demo")
clock = pygame.time.Clock()
font = pygame.font.Font(None, 28)

# ===========================
# 加载 PixelFood sprites
# ===========================
SPRITE_PATH = r"C:\Users\hongy\PixelFood\PixelFood\Split"
sprites = {}
for file in os.listdir(SPRITE_PATH):
    if file.endswith(".png"):
        name = file.replace(".png","")
        path = os.path.join(SPRITE_PATH,file)
        img = pygame.image.load(path).convert()
        img.set_colorkey((255,0,255))  # 粉色透明
        sprites[name] = img
print("Loaded sprites:", list(sprites.keys()))

# ===========================
# 颜色 & 数据结构
# ===========================
PINK = (255,192,203)
food_list = ["Eggs","Apple","Avocado"]  # 手动输入列表
food_queue = queue.Queue()  # 摄像头识别队列
inventory = food_list.copy()  # 显示列表

# ===========================
# 按钮类
# ===========================
class Button:
    def __init__(self, rect, text, color=(100,200,100)):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.color = color
        self.clicked = False
        self.render_text = font.render(text, True, (0,0,0))
    def draw(self, surf):
        pygame.draw.rect(surf, self.color, self.rect)
        surf.blit(self.render_text, (self.rect.x+10, self.rect.y+10))
    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.clicked = True

# ===========================
# 摄像头线程
# ===========================
cv_queue = queue.Queue()
CAM_WIDTH, CAM_HEIGHT = 320,240

def camera_thread():
    cap = cv2.VideoCapture(0)
    while True:
        ret, frame = cap.read()
        if ret:
            cv_queue.put(frame)
        if cv_queue.qsize() > 1:
            cv_queue.get()

threading.Thread(target=camera_thread, daemon=True).start()

# ===========================
# 模型加载 (YOLOv5 COCO)
# ===========================
model = torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True)
model.eval()

# ===========================
# 手动输入
# ===========================
input_text = ""
input_active = True

# ===========================
# CV 检测确认
# ===========================
confirm_food = None
confirm_button = None

running = True
while running:
    screen.fill(PINK)

    # -------------------
    # 手动输入 UI
    # -------------------
    if input_active:
        prompt = font.render("请输入食物名称 (输入后按 ENTER):", True, (0,0,0))
        screen.blit(prompt, (50, 20))
        input_display = font.render(input_text, True, (0,0,0))
        input_box = pygame.Rect(50,50,300,40)
        pygame.draw.rect(screen, (255,255,255), input_box)
        pygame.draw.rect(screen, (0,0,0), input_box,2)
        screen.blit(input_display, (60,60))

    # -------------------
    # 渲染 inventory grid
    # -------------------
    x0 = 50
    y0 = 150
    CELL_SIZE = 80
    COLS = 4
    x = x0
    y = y0
    col = 0
    for food in inventory:
        key = food.lower()
        if key in sprites:
            img = pygame.transform.scale(sprites[key], (64,64))
            screen.blit(img, (x,y))
            col += 1
            x += CELL_SIZE
            if col >= COLS:
                col = 0
                x = x0
                y += CELL_SIZE

    # -------------------
    # 处理摄像头输出
    # -------------------
    cam_frame = None
    if not cv_queue.empty():
        cam_frame = cv_queue.get()
        img = cv2.cvtColor(cam_frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img)

        if confirm_food is None:
            results = model(pil_img)
            df = results.pandas().xyxy[0]
            df = df[df['name'] != 'person']  # 过滤 person
            if not df.empty:
                top = df.iloc[0]
                if top['confidence'] > 0.7:
                    confirm_food = top['name']
                    confirm_button = Button((500,400,200,50), f"Add {confirm_food}?")

    # -------------------
    # 绘制摄像头小窗口
    # -------------------
    if cam_frame is not None:
        cam_frame = cv2.cvtColor(cam_frame, cv2.COLOR_BGR2RGB)
        cam_frame = cv2.resize(cam_frame, (CAM_WIDTH,CAM_HEIGHT))
        cam_surf = pygame.surfarray.make_surface(np.flipud(np.rot90(cam_frame)))
        screen.blit(cam_surf, (450,20))

    # -------------------
    # 绘制确认按钮
    # -------------------
    if confirm_button:
        confirm_button.draw(screen)

    pygame.display.update()
    clock.tick(30)

    # -------------------
    # 事件处理
    # -------------------
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            if input_active:
                if event.key == pygame.K_RETURN:
                    if input_text:
                        key = input_text.lower()
                        if key in sprites:
                            inventory.append(input_text)
                            print(f"手动添加: {input_text}")
                        else:
                            print(f"警告: {input_text} 未找到 sprite")
                        input_text = ""
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                else:
                    input_text += event.unicode
        if confirm_button:
            confirm_button.handle_event(event)
            if confirm_button.clicked:
                inventory.append(confirm_food)
                print(f"摄像头确认添加: {confirm_food}")
                confirm_food = None
                confirm_button = None

pygame.quit()
exit()