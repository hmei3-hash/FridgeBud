import pygame
import os
import cv2
import torch
import torchvision.transforms as transforms
from transformers import AutoModelForImageClassification
from PIL import Image
import threading
import queue
import numpy as np

# ===========================
# 初始化 Pygame
# ===========================
pygame.init()
screen = pygame.display.set_mode((1200, 700))
pygame.display.set_caption("FridgeBud")
clock = pygame.time.Clock()
font_large  = pygame.font.Font(None, 32)
font_medium = pygame.font.Font(None, 24)
font_small  = pygame.font.Font(None, 20)

# ===========================
# 加载 PixelFood sprites
# ===========================
SPRITE_PATH = r"C:\Users\hongy\Desktop\Frig\Free_pixel_food_16x16\Icons"
sprites = {}
for file in os.listdir(SPRITE_PATH):
    if file.endswith(".png"):
        name = file.replace(".png", "")
        img = pygame.image.load(os.path.join(SPRITE_PATH, file)).convert_alpha()
        sprites[name] = img
print("Loaded sprites:", list(sprites.keys()))

# ===========================
# 模型标签 → sprite key 映射
# 模型支持的36类（全小写）：
# apple, banana, beetroot, bell pepper, cabbage, capsicum, carrot,
# cauliflower, chilli pepper, corn, cucumber, eggplant, garlic, ginger,
# grapes, jalapeno, kiwi, lemon, lettuce, mango, onion, orange, paprika,
# pear, peas, pineapple, pomegranate, potato, raddish, soy beans,
# spinach, sweetcorn, sweetpotato, tomato, turnip, watermelon
# ===========================
LABEL_TO_SPRITE = {
    "apple":        "apple",
    "banana":       "banana",
    "carrot":       "carrot",
    "cucumber":     "cucumber",
    "eggplant":     "eggplant",
    "garlic":       "garlic",
    "grapes":       "grapes",
    "kiwi":         "kiwi",
    "lemon":        "lemon",
    "mango":        "mango",
    "onion":        "onion",
    "orange":       "orange",
    "pear":         "pear",
    "pineapple":    "pineapple",
    "potato":       "potato",
    "strawberry":   "strawberry",
    "tomato":       "tomato",
    "watermelon":   "watermelon",
    "corn":         "corn",
    "peach":        "peach",
    "cherry":       "cherry",
    "ginger":       "ginger",
    "cabbage":      "cabbage",
    "bell pepper":  "pepper",
    "capsicum":     "pepper",
    "chilli pepper":"pepper",
    "jalapeno":     "pepper",
    "paprika":      "pepper",
    "pomegranate":  "pomegranate",
}

def label_to_sprite(label: str):
    """把模型输出的标签转成 sprite key（不区分大小写）"""
    label_lower = label.lower().strip()
    # 精确匹配
    if label_lower in LABEL_TO_SPRITE:
        candidate = LABEL_TO_SPRITE[label_lower]
        # 在已加载 sprites 中找（不区分大小写）
        for sk in sprites:
            if sk.lower() == candidate.lower():
                return sk
    # 模糊：标签词在 sprite 名里，或 sprite 名在标签词里
    for sk in sprites:
        if sk.lower() in label_lower or label_lower in sk.lower():
            return sk
    return None

CONFIDENCE_THRESHOLD = 0.60  # 低于此值不弹窗

# ===========================
# 颜色
# ===========================
PINK       = (255, 192, 203)
LIGHT_GRAY = (240, 240, 240)
DARK_GRAY  = (100, 100, 100)
BLACK      = (0,   0,   0  )
WHITE      = (255, 255, 255)
GREEN      = (50,  200, 50 )
RED        = (200, 50,  50 )
YELLOW     = (255, 200, 0  )

# ===========================
# 按钮类（原版）
# ===========================
class Button:
    def __init__(self, rect, text, color=(100, 200, 100)):
        self.rect        = pygame.Rect(rect)
        self.text        = text
        self.color       = color
        self.hover_color = tuple(min(c + 30, 255) for c in color)
        self.clicked     = False
        self.is_hovering = False
        self.render_text = font_medium.render(text, True, BLACK)

    def draw(self, surf):
        color = self.hover_color if self.is_hovering else self.color
        pygame.draw.rect(surf, color, self.rect)
        pygame.draw.rect(surf, BLACK, self.rect, 2)
        surf.blit(self.render_text, self.render_text.get_rect(center=self.rect.center))

    def update(self, mouse_pos):
        self.is_hovering = self.rect.collidepoint(mouse_pos)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                self.clicked = True

# ===========================
# 摄像头线程（原版）
# ===========================
cv_queue = queue.Queue()
CAM_WIDTH, CAM_HEIGHT = 320, 240

def camera_thread():
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("无法打开摄像头")
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
# 加载 Hugging Face 水果蔬菜模型
# jazzmacedo/fruits-and-vegetables-detector-36
# ResNet-50 微调，97% 准确率，36种水果蔬菜
# 首次运行自动下载（~90MB），之后本地缓存
# ===========================
print("加载水果蔬菜识别模型（首次运行会自动下载）...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

hf_model = AutoModelForImageClassification.from_pretrained(
    "jazzmacedo/fruits-and-vegetables-detector-36"
)
hf_model.to(device)
hf_model.eval()

# 从模型配置里拿标签列表（保证顺序和训练时一致）
HF_LABELS = list(hf_model.config.id2label.values())
print(f"✓ 模型加载完成，支持 {len(HF_LABELS)} 类: {HF_LABELS}")

preprocess = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])

def classify_frame(frame_bgr):
    """返回 (label, confidence)"""
    rgb    = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    tensor = preprocess(Image.fromarray(rgb)).unsqueeze(0).to(device)
    with torch.no_grad():
        logits = hf_model(tensor).logits
        probs  = torch.softmax(logits, dim=1)
        conf, idx = torch.max(probs, dim=1)
    return HF_LABELS[idx.item()], conf.item()

# ===========================
# 检测后台线程
# ===========================
detect_result_queue = queue.Queue(maxsize=1)

def detection_thread():
    import time
    while True:
        if not cv_queue.empty():
            frame = list(cv_queue.queue)[-1]  # 最新帧
            label, conf = classify_frame(frame)
            if conf >= CONFIDENCE_THRESHOLD:
                if detect_result_queue.full():
                    try: detect_result_queue.get_nowait()
                    except: pass
                detect_result_queue.put((label, conf))
        time.sleep(0.15)  # ~6fps

threading.Thread(target=detection_thread, daemon=True).start()

# ===========================
# 状态
# ===========================
ALL_FOODS  = sorted(sprites.keys())
inventory  = []
input_text = ""
input_active        = True
suggestions         = []
selected_suggestion = -1

confirm_food        = None   # sprite key
confirm_label       = None   # 模型原始标签
confirm_button      = None
last_detection      = None
detection_confidence = 0.0

# ===========================
# 主循环
# ===========================
running = True
while running:
    screen.fill(PINK)
    mouse_pos = pygame.mouse.get_pos()

    # ---------- 左侧：输入 + 库存 ----------
    screen.blit(font_large.render("FridgeBud", True, BLACK), (50, 20))

    if input_active:
        screen.blit(font_medium.render("搜索或输入:", True, BLACK), (50, 70))
        suggestions = [f for f in ALL_FOODS
                       if f.lower().startswith(input_text.lower())][:5] if input_text else []

        input_box = pygame.Rect(50, 110, 300, 45)
        pygame.draw.rect(screen, WHITE, input_box)
        pygame.draw.rect(screen, BLACK, input_box, 2)
        display = input_text if input_text else "输入食物..."
        screen.blit(font_large.render(display, True, BLACK if input_text else DARK_GRAY), (65, 120))

        for i, sugg in enumerate(suggestions):
            bg = YELLOW if i == selected_suggestion else LIGHT_GRAY
            pygame.draw.rect(screen, bg, (50, 165 + i * 25, 300, 25))
            pygame.draw.rect(screen, BLACK, (50, 165 + i * 25, 300, 25), 1)
            screen.blit(font_small.render(sugg, True, BLACK), (60, 170 + i * 25))

    screen.blit(font_medium.render("库存 (Inventory)", True, BLACK), (50, 320))

    x0, y0, CELL_SIZE, COLS = 50, 360, 100, 3
    x, y, col = x0, y0, 0
    for food in inventory:
        if food in sprites:
            screen.blit(pygame.transform.scale(sprites[food], (64, 64)), (x, y))
            screen.blit(font_small.render(food[:10], True, BLACK), (x, y + 70))
            col += 1; x += CELL_SIZE
            if col >= COLS:
                col, x, y = 0, x0, y + CELL_SIZE + 10

    # ---------- 右侧：摄像头 + 识别 ----------
    screen.blit(font_medium.render("摄像头识别 (水果蔬菜专用)", True, BLACK), (650, 20))

    cam_frame = None
    if not cv_queue.empty():
        cam_frame = cv_queue.get()
    if cam_frame is not None:
        disp = cv2.cvtColor(cv2.resize(cam_frame, (CAM_WIDTH, CAM_HEIGHT)), cv2.COLOR_BGR2RGB)
        screen.blit(pygame.surfarray.make_surface(np.flipud(np.rot90(disp))), (650, 70))

    # 拉取后台识别结果
    if confirm_food is None and not detect_result_queue.empty():
        raw_label, conf = detect_result_queue.get()
        last_detection       = raw_label
        detection_confidence = conf
        sprite_key = label_to_sprite(raw_label)
        if sprite_key:
            confirm_food   = sprite_key
            confirm_label  = raw_label
            confirm_button = Button((650, 500, 260, 50), f"Add {sprite_key}?", GREEN)
            print(f"检测: {raw_label} ({conf:.0%}) → sprite: {sprite_key}")
        else:
            print(f"检测: {raw_label} ({conf:.0%}) — 无对应 sprite")

    # 实时标签显示
    if last_detection:
        conf_color = GREEN if detection_confidence > 0.80 else YELLOW
        screen.blit(font_small.render(f"识别: {last_detection}", True, BLACK), (650, 325))
        screen.blit(font_small.render(f"置信度: {detection_confidence:.0%}", True, conf_color), (650, 348))

    if confirm_button:
        confirm_button.update(mouse_pos)
        confirm_button.draw(screen)
        screen.blit(font_small.render("ESC 跳过", True, DARK_GRAY), (650, 560))

    screen.blit(font_small.render("ENTER: 添加  |  ESC: 跳过  |  ↑↓: 选择建议", True, DARK_GRAY), (50, 670))

    pygame.display.update()
    clock.tick(30)

    # ---------- 事件 ----------
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if confirm_food:
                    confirm_food = confirm_button = None
                else:
                    running = False

            if input_active:
                if event.key == pygame.K_RETURN:
                    if suggestions and selected_suggestion >= 0:
                        food = suggestions[selected_suggestion]
                        if food not in inventory:
                            inventory.append(food)
                            print(f"✓ 手动添加: {food}")
                        input_text, selected_suggestion = "", -1
                    elif input_text and input_text in sprites:
                        if input_text not in inventory:
                            inventory.append(input_text)
                            print(f"✓ 手动添加: {input_text}")
                        input_text, selected_suggestion = "", -1
                    else:
                        print(f"✗ 找不到: {input_text}")
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]; selected_suggestion = -1
                elif event.key == pygame.K_UP:
                    selected_suggestion = max(-1, selected_suggestion - 1)
                elif event.key == pygame.K_DOWN:
                    selected_suggestion = min(len(suggestions) - 1, selected_suggestion + 1)
                elif event.unicode.isalpha() or event.unicode == " ":
                    input_text += event.unicode; selected_suggestion = -1

        if confirm_button:
            confirm_button.handle_event(event)
            if confirm_button.clicked:
                if confirm_food not in inventory:
                    inventory.append(confirm_food)
                    print(f"✓ 摄像头添加: {confirm_food} (识别: {confirm_label})")
                confirm_food = confirm_button = None

pygame.quit()
exit()