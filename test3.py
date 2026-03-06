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
screen = pygame.display.set_mode((1200, 700))
pygame.display.set_caption("FridgeBud Food + CV Demo (Improved)")
clock = pygame.time.Clock()
font_large = pygame.font.Font(None, 32)
font_medium = pygame.font.Font(None, 24)
font_small = pygame.font.Font(None, 20)

# ===========================
# 加载 PixelFood sprites
# ===========================
SPRITE_PATH = r"C:\Users\hongy\PixelFood\PixelFood\Split"
sprites = {}
for file in os.listdir(SPRITE_PATH):
    if file.endswith(".png"):
        name = file.replace(".png", "")
        path = os.path.join(SPRITE_PATH, file)
        img = pygame.image.load(path).convert()
        img.set_colorkey((255, 0, 255))  # 粉色透明
        sprites[name] = img
print("Loaded sprites:", list(sprites.keys()))

# ===========================
# COCO 到 PixelFood 的映射表
# ===========================
COCO_TO_PIXEL = {
    # 水果
    'apple': 'Apple',
    'banana': 'Banana',  # 如果没有就跳过
    'orange': 'Orange',
    'strawberry': 'Strawberry',
    'kiwi': 'Kiwi',
    'pineapple': 'Pineapple',
    'peach': 'Peach',
    'cherry': 'Cherry',
    'dragon fruit': 'DragonFruit',
    'watermelon': 'MelonWater',
    'cantaloup': 'MelonCantaloupe',
    'honeydew': 'MelonHoneydew',
    
    # 蔬菜
    'broccoli': 'Broccoli',
    'carrot': 'Carrot',
    'potato': 'Potato',
    'tomato': 'Tomato',
    'onion': 'Onion',
    'eggplant': 'Eggplant',
    
    # 肉类
    'chicken': 'Chicken',
    'cow': 'Steak',
    'sheep': 'Lamb',
    'pig': 'Boar',
    'hot dog': 'Sausages',
    'pizza': 'Pizza',
    'hamburger': 'Hamburger',
    'sandwich': 'Sandwich',
    
    # 海鲜
    'fish': 'Fish',
    'shrimp': 'Shrimp',
    
    # 面包/糕点
    'bread': 'Bread',
    'cake': 'Cake',
    'donut': 'Donut',
    'cookie': 'Cookie',
    'waffle': 'Waffles',
    
    # 饮品
    'wine glass': 'Wine',
    'cup': 'Cup',
    'bottle': 'Beer',
    
    # 乳制品
    'cheese': 'Cheese',
    'milk': 'Milk',
}

# ===========================
# 颜色定义
# ===========================
PINK = (255, 192, 203)
LIGHT_GRAY = (240, 240, 240)
DARK_GRAY = (100, 100, 100)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (50, 200, 50)
RED = (200, 50, 50)
YELLOW = (255, 200, 0)

# ===========================
# 按钮类
# ===========================
class Button:
    def __init__(self, rect, text, color=(100, 200, 100)):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.color = color
        self.hover_color = tuple(min(c + 30, 255) for c in color)
        self.clicked = False
        self.is_hovering = False
        self.render_text = font_medium.render(text, True, BLACK)
        
    def draw(self, surf):
        color = self.hover_color if self.is_hovering else self.color
        pygame.draw.rect(surf, color, self.rect)
        pygame.draw.rect(surf, BLACK, self.rect, 2)
        text_rect = self.render_text.get_rect(center=self.rect.center)
        surf.blit(self.render_text, text_rect)
        
    def update(self, mouse_pos):
        self.is_hovering = self.rect.collidepoint(mouse_pos)
        
    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.clicked = True

# ===========================
# 摄像头线程
# ===========================
cv_queue = queue.Queue()
CAM_WIDTH, CAM_HEIGHT = 320, 240

def camera_thread():
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("⚠ 无法打开摄像头")
            return
        while True:
            ret, frame = cap.read()
            if ret:
                cv_queue.put(frame)
            if cv_queue.qsize() > 2:
                cv_queue.get()
    except Exception as e:
        print(f"摄像头错误: {e}")

threading.Thread(target=camera_thread, daemon=True).start()

# ===========================
# 模型加载 (YOLOv5 COCO)
# ===========================
print("加载 YOLOv5 模型...")
try:
    model = torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True)
    model.eval()
    model_loaded = True
    print("✓ 模型加载成功")
except Exception as e:
    print(f"✗ 模型加载失败: {e}")
    model_loaded = False

# ===========================
# 初始库存
# ===========================
ALL_FOODS = ['Apple', 'AppleWorm', 'Avocado', 'Bacon', 'Beer', 'Boar', 'Bread', 'Brownie', 'Bug', 
             'Cheese', 'Cherry', 'Chicken', 'ChickenLeg', 'Cookie', 'DragonFruit', 'Eggplant', 'Eggs', 
             'Fish', 'FishFillet', 'FishSteak', 'Grub', 'Grubs', 'Honey', 'Honeycomb', 'Jam', 'Jerky', 
             'Kiwi', 'Marmalade', 'MelonCantaloupe', 'MelonHoneydew', 'MelonWater', 'Moonshine', 'Olive', 
             'Onion', 'Peach', 'PepperGreen', 'Pepperoni', 'PepperRed', 'Pickle', 'PickledEggs', 
             'PieApple', 'PieLemon', 'PiePumpkin', 'Pineapple', 'Potato', 'PotatoRed', 'Pretzel', 'Ribs', 
             'Roll', 'Sake', 'Sardines', 'Sashimi', 'Sausages', 'Shrimp', 'Steak', 'Stein', 'Strawberry', 
             'Sushi', 'Tart', 'Tomato', 'Turnip', 'Waffles', 'Whiskey', 'Wine']

inventory = ["Eggs", "Apple", "Avocado"]  # 初始库存
input_text = ""
input_active = True
suggestions = []
selected_suggestion = -1

# CV 检测
confirm_food = None
confirm_button = None
last_detection = None
detection_confidence = 0

running = True
while running:
    screen.fill(PINK)
    mouse_pos = pygame.mouse.get_pos()

    # ===========================
    # 左侧：手动输入和库存
    # ===========================
    
    # 标题
    title = font_large.render("FridgeBud", True, BLACK)
    screen.blit(title, (50, 20))
    
    # 手动输入
    if input_active:
        prompt = font_medium.render("搜索或输入:", True, BLACK)
        screen.blit(prompt, (50, 70))
        
        suggestions = []
        if input_text:
            suggestions = [f for f in ALL_FOODS 
                          if f.lower().startswith(input_text.lower()) 
                          and f in sprites][:5]
        
        input_display = font_large.render(input_text if input_text else "输入食物...", True, 
                                         DARK_GRAY if not input_text else BLACK)
        input_box = pygame.Rect(50, 110, 300, 45)
        pygame.draw.rect(screen, WHITE, input_box)
        pygame.draw.rect(screen, BLACK, input_box, 2)
        screen.blit(input_display, (65, 120))
        
        # 建议列表
        if suggestions:
            for i, sugg in enumerate(suggestions):
                color = YELLOW if i == selected_suggestion else LIGHT_GRAY
                pygame.draw.rect(screen, color, (50, 165 + i*25, 300, 25))
                pygame.draw.rect(screen, BLACK, (50, 165 + i*25, 300, 25), 1)
                sugg_text = font_small.render(sugg, True, BLACK)
                screen.blit(sugg_text, (60, 170 + i*25))
    
    # 库存标签
    inv_title = font_medium.render("库存 (Inventory)", True, BLACK)
    screen.blit(inv_title, (50, 320))
    
    # 库存网格
    x0, y0 = 50, 360
    CELL_SIZE = 100
    COLS = 3
    x, y = x0, y0
    col = 0
    
    for food in inventory:
        if food in sprites:
            img = pygame.transform.scale(sprites[food], (64, 64))
            screen.blit(img, (x, y))
            
            # 显示食物名称
            name_text = font_small.render(food[:10], True, BLACK)
            screen.blit(name_text, (x, y + 70))
            
            col += 1
            x += CELL_SIZE
            if col >= COLS:
                col = 0
                x = x0
                y += CELL_SIZE + 10

    # ===========================
    # 右侧：摄像头和检测
    # ===========================
    
    cam_label = font_medium.render("摄像头识别", True, BLACK)
    screen.blit(cam_label, (650, 20))
    
    # 处理摄像头输出
    cam_frame = None
    if not cv_queue.empty():
        cam_frame = cv_queue.get()
        
        if model_loaded and confirm_food is None:
            try:
                img = cv2.cvtColor(cam_frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img)
                
                # 正确的方式：设置模型置信度
                model.conf = 0.3
                model.iou = 0.45
                results = model(pil_img)
                df = results.pandas().xyxy[0]
                
                # 过滤掉 person
                df = df[df['name'] != 'person']
                
                if not df.empty:
                    # 按置信度排序
                    df = df.sort_values('confidence', ascending=False)
                    top = df.iloc[0]
                    
                    coco_label = top['name'].lower()
                    detection_confidence = float(top['confidence'])
                    
                    # 尝试映射到 PixelFood
                    pixel_food = None
                    for coco_key, pixel_key in COCO_TO_PIXEL.items():
                        if coco_key in coco_label or coco_label in coco_key:
                            if pixel_key in sprites:
                                pixel_food = pixel_key
                                break
                    
                    # 如果直接匹配
                    if not pixel_food:
                        for food in ALL_FOODS:
                            if food.lower() == coco_label:
                                pixel_food = food
                                break
                    
                    if pixel_food and detection_confidence > 0.4:
                        confirm_food = pixel_food
                        last_detection = coco_label
                        confirm_button = Button((650, 500, 200, 50), f"Add {pixel_food}?", GREEN)
                        
            except Exception as e:
                print(f"检测错误: {e}")
    
    # 绘制摄像头画面
    if cam_frame is not None:
        cam_frame = cv2.cvtColor(cam_frame, cv2.COLOR_BGR2RGB)
        cam_frame = cv2.resize(cam_frame, (CAM_WIDTH, CAM_HEIGHT))
        cam_surf = pygame.surfarray.make_surface(np.flipud(np.rot90(cam_frame)))
        screen.blit(cam_surf, (650, 70))
        
        # 置信度显示
        if detection_confidence > 0:
            conf_text = font_small.render(f"检测: {last_detection if last_detection else 'N/A'}", True, BLACK)
            screen.blit(conf_text, (650, 320))
            conf_bar_text = font_small.render(f"置信度: {detection_confidence:.1%}", True, 
                                             GREEN if detection_confidence > 0.6 else YELLOW)
            screen.blit(conf_bar_text, (650, 345))
    
    # 绘制确认按钮
    if confirm_button:
        confirm_button.update(mouse_pos)
        confirm_button.draw(screen)
    
    # 提示信息
    hint = font_small.render("ENTER: 添加  |  ESC: 跳过  |  ↑↓: 选择建议", True, DARK_GRAY)
    screen.blit(hint, (50, 650))

    pygame.display.update()
    clock.tick(30)

    # ===========================
    # 事件处理
    # ===========================
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
            
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if confirm_food:
                    confirm_food = None
                    confirm_button = None
                    detection_confidence = 0
                else:
                    running = False
            
            if input_active:
                if event.key == pygame.K_RETURN:
                    if suggestions and selected_suggestion >= 0:
                        # 选择建议
                        food = suggestions[selected_suggestion]
                        if food not in inventory:
                            inventory.append(food)
                            print(f"✓ 添加: {food}")
                        input_text = ""
                        selected_suggestion = -1
                    elif input_text and input_text in sprites:
                        # 手动输入
                        if input_text not in inventory:
                            inventory.append(input_text)
                            print(f"✓ 添加: {input_text}")
                        else:
                            print(f"⚠ {input_text} 已在库存中")
                        input_text = ""
                        selected_suggestion = -1
                    else:
                        print(f"✗ 找不到: {input_text}")
                
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                    selected_suggestion = -1
                
                elif event.key == pygame.K_UP:
                    selected_suggestion = max(-1, selected_suggestion - 1)
                
                elif event.key == pygame.K_DOWN:
                    selected_suggestion = min(len(suggestions) - 1, selected_suggestion + 1)
                
                elif event.unicode.isalpha():
                    input_text += event.unicode
                    selected_suggestion = -1
        
        if confirm_button:
            confirm_button.handle_event(event)
            if confirm_button.clicked:
                if confirm_food not in inventory:
                    inventory.append(confirm_food)
                    print(f"✓ 摄像头添加: {confirm_food} (检测: {last_detection})")
                confirm_food = None
                confirm_button = None
                detection_confidence = 0

pygame.quit()
exit()