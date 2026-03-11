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
import math
import random
import time

# ===========================
# 初始化 Pygame
# ===========================
pygame.init()
W, H = 1200, 700
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("FridgeBud")
clock = pygame.time.Clock()
font_large  = pygame.font.Font(None, 32)
font_medium = pygame.font.Font(None, 24)
font_small  = pygame.font.Font(None, 20)
font_xl     = pygame.font.Font(None, 72)
font_xxl    = pygame.font.Font(None, 110)

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

# 找 orange sprite（不区分大小写）
ORANGE_KEY = None
for sk in sprites:
    if "orange" in sk.lower():
        ORANGE_KEY = sk
        break
if ORANGE_KEY is None:
    # 如果没有，创建一个橙色圆形作为替代
    ORANGE_KEY = "_orange"
    surf = pygame.Surface((32, 32), pygame.SRCALPHA)
    pygame.draw.circle(surf, (255, 140, 0), (16, 16), 14)
    pygame.draw.circle(surf, (200, 100, 0), (16, 16), 14, 2)
    sprites[ORANGE_KEY] = surf

print(f"Orange sprite key: {ORANGE_KEY}")

# ===========================
# 颜色
# ===========================
PINK        = (255, 192, 203)
LIGHT_GRAY  = (240, 240, 240)
DARK_GRAY   = (100, 100, 100)
BLACK       = (0,   0,   0  )
WHITE       = (255, 255, 255)
GREEN       = (50,  200, 50 )
RED         = (200, 50,  50 )
YELLOW      = (255, 200, 0  )
ORANGE      = (255, 140, 0  )
BAG_BROWN   = (139, 90,  43 )
BAG_DARK    = (100, 60,  20 )
BAG_LIGHT   = (180, 130, 70 )

# ===========================
# 袋子参数
# ===========================
BAG_X       = 820   # 袋子中心 x
BAG_Y       = 420   # 袋子开口 y
BAG_W       = 160   # 袋子宽
BAG_H       = 180   # 袋子高
BAG_MOUTH_Y = BAG_Y  # 开口 y（橙子飞入目标）

# ===========================
# 物理橙子粒子
# ===========================
class FlyingOrange:
    """从左侧飞向袋子的橙子动画"""
    def __init__(self, start_x, start_y, target_x, target_y):
        self.x  = float(start_x)
        self.y  = float(start_y)
        self.tx = float(target_x)
        self.ty = float(target_y)
        # 抛物线初速度
        self.t      = 0.0
        self.dur    = 0.55  # 飞行秒数
        self.done   = False
        self.angle  = 0.0
        self.spin   = random.uniform(-8, 8)
        # 贝塞尔控制点：制造弧形轨迹
        mid_x = (start_x + target_x) / 2
        mid_y = min(start_y, target_y) - random.randint(80, 160)
        self.p0 = (start_x, start_y)
        self.p1 = (mid_x, mid_y)
        self.p2 = (target_x, target_y)
        # 拖尾
        self.trail = []
        # 大小变化（飞近变大）
        self.base_size = 28

    def bezier(self, t):
        x = (1-t)**2 * self.p0[0] + 2*(1-t)*t * self.p1[0] + t**2 * self.p2[0]
        y = (1-t)**2 * self.p0[1] + 2*(1-t)*t * self.p1[1] + t**2 * self.p2[1]
        return x, y

    def update(self, dt):
        if self.done:
            return
        self.t = min(self.t + dt / self.dur, 1.0)
        self.angle += self.spin
        old_x, old_y = self.x, self.y
        self.x, self.y = self.bezier(self.t)
        self.trail.append((self.x, self.y))
        if len(self.trail) > 12:
            self.trail.pop(0)
        if self.t >= 1.0:
            self.done = True

    def draw(self, surf):
        # 拖尾
        for i, (tx, ty) in enumerate(self.trail):
            alpha = int(180 * (i / len(self.trail)))
            r = max(3, int(8 * (i / len(self.trail))))
            tsurf = pygame.Surface((r*2, r*2), pygame.SRCALPHA)
            pygame.draw.circle(tsurf, (255, 160, 30, alpha), (r, r), r)
            surf.blit(tsurf, (int(tx)-r, int(ty)-r))
        # 橙子本体
        size = int(self.base_size * (0.6 + 0.4 * self.t))
        orange_surf = pygame.transform.scale(sprites[ORANGE_KEY], (size, size))
        orange_surf = pygame.transform.rotate(orange_surf, self.angle)
        rect = orange_surf.get_rect(center=(int(self.x), int(self.y)))
        surf.blit(orange_surf, rect)


class BounceParticle:
    """橙子入袋后的弹出粒子"""
    def __init__(self, x, y):
        angle = random.uniform(-math.pi, 0)  # 向上弹
        speed = random.uniform(2, 7)
        self.x  = float(x)
        self.y  = float(y)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.life = 1.0
        self.color = random.choice([ORANGE, YELLOW, (255,200,80), (255,100,0)])
        self.r = random.randint(3, 8)

    def update(self, dt):
        self.vy += 12 * dt  # 重力
        self.x  += self.vx
        self.y  += self.vy
        self.life -= dt * 2.5

    def draw(self, surf):
        if self.life <= 0:
            return
        alpha = int(255 * max(0, self.life))
        s = pygame.Surface((self.r*2, self.r*2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.color, alpha), (self.r, self.r), self.r)
        surf.blit(s, (int(self.x)-self.r, int(self.y)-self.r))


class BagShake:
    """袋子晃动效果"""
    def __init__(self):
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.timer    = 0.0
        self.active   = False

    def trigger(self):
        self.timer  = 0.4
        self.active = True

    def update(self, dt):
        if not self.active:
            return
        self.timer -= dt
        if self.timer <= 0:
            self.active   = False
            self.offset_x = 0
            self.offset_y = 0
        else:
            decay = self.timer / 0.4
            self.offset_x = math.sin(self.timer * 50) * 6 * decay
            self.offset_y = math.sin(self.timer * 40) * 3 * decay

# ===========================
# 绘制袋子
# ===========================
def draw_bag(surf, shake, orange_count):
    ox = shake.offset_x
    oy = shake.offset_y
    bx = BAG_X + ox
    by = BAG_Y + oy

    # 袋子主体（梯形）
    body_pts = [
        (bx - BAG_W//2 + 10, by),          # 左开口
        (bx + BAG_W//2 - 10, by),          # 右开口
        (bx + BAG_W//2 - 5,  by + BAG_H),  # 右底
        (bx - BAG_W//2 + 5,  by + BAG_H),  # 左底
    ]
    pygame.draw.polygon(surf, BAG_BROWN, body_pts)
    pygame.draw.polygon(surf, BAG_DARK,  body_pts, 3)

    # 袋子折叠线（质感）
    fold_y = by + 30
    pygame.draw.line(surf, BAG_LIGHT,
                     (bx - BAG_W//2 + 15, fold_y),
                     (bx + BAG_W//2 - 15, fold_y), 2)
    fold_y2 = by + 60
    pygame.draw.line(surf, BAG_LIGHT,
                     (bx - BAG_W//2 + 20, fold_y2),
                     (bx + BAG_W//2 - 20, fold_y2), 1)

    # 袋子开口边缘（卷边）
    roll_pts = [
        (bx - BAG_W//2,      by - 12),
        (bx - BAG_W//2 + 10, by),
        (bx + BAG_W//2 - 10, by),
        (bx + BAG_W//2,      by - 12),
    ]
    pygame.draw.polygon(surf, BAG_LIGHT, roll_pts)
    pygame.draw.polygon(surf, BAG_DARK,  roll_pts, 2)

    # 袋子底部圆角
    pygame.draw.ellipse(surf, BAG_DARK,
                        (bx - BAG_W//2 + 5, by + BAG_H - 12,
                         BAG_W - 10, 20), 2)

    # 橙子堆在袋子里（小图标）
    if orange_count > 0:
        icon_size = 22
        cols = 4
        for i in range(min(orange_count, 12)):
            row = i // cols
            col = i % cols
            ix = bx - BAG_W//2 + 25 + col * 28
            iy = by + BAG_H - 30 - row * 24
            mini = pygame.transform.scale(sprites[ORANGE_KEY], (icon_size, icon_size))
            surf.blit(mini, (int(ix), int(iy)))

    # 橙子数量标签
    if orange_count > 0:
        count_surf = font_large.render(f"x{orange_count}", True, WHITE)
        surf.blit(count_surf, (int(bx + BAG_W//2 - 10), int(by + BAG_H - 35)))


# ===========================
# 绘制队列显示
# ===========================
def draw_queue_display(surf, orange_count):
    """右下角：橙子图标 + x数量"""
    qx, qy = 650, 570
    surf.blit(font_medium.render("购物队列:", True, BLACK), (qx, qy - 25))
    if orange_count > 0:
        icon = pygame.transform.scale(sprites[ORANGE_KEY], (48, 48))
        surf.blit(icon, (qx, qy))
        count_text = font_xl.render(f"x{orange_count}", True, ORANGE)
        surf.blit(count_text, (qx + 58, qy + 4))
    else:
        surf.blit(font_medium.render("—", True, DARK_GRAY), (qx, qy + 10))


# ===========================
# OK 按钮
# ===========================
class OKButton:
    def __init__(self):
        self.rect     = pygame.Rect(1010, 570, 140, 60)
        self.hovered  = False
        self.clicked  = False
        self.pulse    = 0.0  # 脉冲动画相位

    def update(self, dt, mouse_pos):
        self.hovered = self.rect.collidepoint(mouse_pos)
        self.pulse  += dt * 3

    def draw(self, surf):
        pulse_scale = 1.0 + 0.04 * math.sin(self.pulse)
        w = int(self.rect.width  * pulse_scale)
        h = int(self.rect.height * pulse_scale)
        rx = self.rect.centerx - w // 2
        ry = self.rect.centery - h // 2
        r  = pygame.Rect(rx, ry, w, h)

        color = (30, 180, 30) if self.hovered else (50, 160, 50)
        pygame.draw.rect(surf, color, r, border_radius=12)
        pygame.draw.rect(surf, (20, 120, 20), r, 3, border_radius=12)

        label = font_large.render("✓ OK", True, WHITE)
        surf.blit(label, label.get_rect(center=r.center))

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
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("无法打开摄像头"); return
    while True:
        ret, frame = cap.read()
        if ret:
            cv_queue.put(frame)
        if cv_queue.qsize() > 2:
            cv_queue.get()

threading.Thread(target=camera_thread, daemon=True).start()

# ===========================
# 加载 HuggingFace 水果模型
# ===========================
print("加载水果识别模型...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
hf_model = AutoModelForImageClassification.from_pretrained(
    "jazzmacedo/fruits-and-vegetables-detector-36"
)
hf_model.to(device)
hf_model.eval()
HF_LABELS = list(hf_model.config.id2label.values())
print(f"✓ 模型加载完成，支持: {HF_LABELS}")

preprocess = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

def classify_frame(frame_bgr):
    rgb    = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    tensor = preprocess(Image.fromarray(rgb)).unsqueeze(0).to(device)
    with torch.no_grad():
        probs = torch.softmax(hf_model(tensor).logits, dim=1)
        conf, idx = torch.max(probs, dim=1)
    return HF_LABELS[idx.item()], conf.item()

# ===========================
# 检测线程
# ===========================
detect_result_queue = queue.Queue(maxsize=1)
CONFIDENCE_THRESHOLD = 0.60

def detection_thread():
    while True:
        if not cv_queue.empty():
            frame = list(cv_queue.queue)[-1]
            label, conf = classify_frame(frame)
            if conf >= CONFIDENCE_THRESHOLD:
                if detect_result_queue.full():
                    try: detect_result_queue.get_nowait()
                    except: pass
                detect_result_queue.put((label, conf))
        time.sleep(0.15)

threading.Thread(target=detection_thread, daemon=True).start()

# ===========================
# 状态
# ===========================
# 橙子检测状态
orange_detected     = False
detection_cooldown  = 0.0   # 检测冷却（防止重复弹窗）
last_label          = ""
last_conf           = 0.0

# 橙子袋
orange_in_bag       = 0

# 动画对象
flying_oranges  = []
particles       = []
bag_shake       = BagShake()
ok_button       = OKButton()

# 点击区域（袋子 + 添加橙子按钮）
add_btn_rect    = pygame.Rect(BAG_X - 80, BAG_Y - 55, 160, 44)

# 状态机
STATE_IDLE      = "idle"       # 等待识别
STATE_DETECTED  = "detected"   # 检测到橙子，显示"点击添加"
STATE_DONE      = "done"       # 按下OK，显示完成

state = STATE_IDLE

# 完成动画
done_particles  = []
done_timer      = 0.0

# ===========================
# 主循环
# ===========================
running = True
dt = 0.0

while running:
    dt = clock.tick(60) / 1000.0
    mouse_pos = pygame.mouse.get_pos()

    # ---- 背景 ----
    screen.fill(PINK)

    # ---- 拉取检测结果 ----
    if state == STATE_IDLE and detection_cooldown <= 0:
        if not detect_result_queue.empty():
            label, conf = detect_result_queue.get()
            last_label = label
            last_conf  = conf
            if "orange" in label.lower():
                state            = STATE_DETECTED
                orange_detected  = True
                detection_cooldown = 2.0

    if detection_cooldown > 0:
        detection_cooldown -= dt

    # ---- 更新动画 ----
    for fo in flying_oranges[:]:
        fo.update(dt)
        if fo.done:
            flying_oranges.remove(fo)
            # 入袋特效
            for _ in range(18):
                particles.append(BounceParticle(BAG_X, BAG_MOUTH_Y))
            bag_shake.trigger()

    for p in particles[:]:
        p.update(dt)
        if p.life <= 0:
            particles.remove(p)

    bag_shake.update(dt)
    ok_button.update(dt, mouse_pos)

    # done 爆炸粒子
    for p in done_particles[:]:
        p.update(dt)
        if p.life <= 0:
            done_particles.remove(p)
    if state == STATE_DONE:
        done_timer -= dt

    # ---- 绘制摄像头 ----
    cam_label_surf = font_medium.render("摄像头识别", True, BLACK)
    screen.blit(cam_label_surf, (50, 20))

    cam_frame = None
    if not cv_queue.empty():
        cam_frame = cv_queue.get()
    if cam_frame is not None:
        disp = cv2.cvtColor(cv2.resize(cam_frame, (CAM_WIDTH, CAM_HEIGHT)), cv2.COLOR_BGR2RGB)
        cam_surf = pygame.surfarray.make_surface(np.flipud(np.rot90(disp)))
        screen.blit(cam_surf, (50, 55))

    # 实时检测标签
    if last_label:
        is_orange = "orange" in last_label.lower()
        lc = GREEN if is_orange else DARK_GRAY
        screen.blit(font_small.render(f"识别: {last_label}  ({last_conf:.0%})", True, lc), (50, 310))

    # ---- 摄像头下方说明 ----
    if state == STATE_IDLE:
        hint = font_medium.render("把橙子对准摄像头...", True, DARK_GRAY)
        screen.blit(hint, (50, 340))
    elif state == STATE_DETECTED:
        # 点击提示（橙色闪烁）
        alpha = int(200 + 55 * math.sin(time.time() * 6))
        hint_surf = font_large.render("🍊 检测到橙子！点击袋子添加", True, ORANGE)
        screen.blit(hint_surf, (50, 340))

    # ---- 绘制袋子 ----
    draw_bag(screen, bag_shake, orange_in_bag)

    # ---- 绘制飞行橙子 ----
    for fo in flying_oranges:
        fo.draw(screen)

    # ---- 绘制粒子 ----
    for p in particles:
        p.draw(screen)

    # ---- 绘制队列显示 ----
    draw_queue_display(screen, orange_in_bag)

    # ---- 点击添加按钮（袋子区域） ----
    if state == STATE_DETECTED:
        # 袋子高亮边框（鼓励点击）
        bag_rect = pygame.Rect(BAG_X - BAG_W//2 - 10 + bag_shake.offset_x,
                               BAG_Y - 20 + bag_shake.offset_y,
                               BAG_W + 20, BAG_H + 30)
        pulse_w = int(3 + 2 * math.sin(time.time() * 8))
        pygame.draw.rect(screen, ORANGE, bag_rect, pulse_w, border_radius=8)

        # 点击提示箭头
        arrow_y = int(BAG_Y - 40 + 5 * math.sin(time.time() * 5))
        arrow_text = font_large.render("▼ 点这里", True, ORANGE)
        screen.blit(arrow_text, (BAG_X - arrow_text.get_width()//2, arrow_y))

    # ---- OK 按钮 ----
    if orange_in_bag > 0 and state != STATE_DONE:
        ok_button.draw(screen)
        screen.blit(font_small.render("结束添加", True, DARK_GRAY),
                    (ok_button.rect.centerx - 25, ok_button.rect.bottom + 5))

    # ---- DONE 状态 ----
    if state == STATE_DONE:
        for p in done_particles:
            p.draw(screen)

        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120))
        screen.blit(overlay, (0, 0))

        done_text = font_xxl.render(f"🍊 x{orange_in_bag}", True, ORANGE)
        sub_text  = font_large.render("已加入购物队列！", True, WHITE)
        screen.blit(done_text, done_text.get_rect(center=(W//2, H//2 - 30)))
        screen.blit(sub_text,  sub_text.get_rect(center=(W//2, H//2 + 60)))

    pygame.display.update()

    # ===========================
    # 事件处理
    # ===========================
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = event.pos

            # 点击袋子区域 → 飞橙子入袋
            bag_click_rect = pygame.Rect(BAG_X - BAG_W//2 - 15,
                                         BAG_Y - 30,
                                         BAG_W + 30, BAG_H + 40)
            if state == STATE_DETECTED and bag_click_rect.collidepoint(mx, my):
                # 从摄像头画面右侧飞出
                start_x = 380 + random.randint(-20, 20)
                start_y = 180 + random.randint(-30, 30)
                flying_oranges.append(
                    FlyingOrange(start_x, start_y, BAG_X, BAG_MOUTH_Y + 10)
                )
                orange_in_bag += 1
                # 重置识别，等下一次点击
                state = STATE_IDLE
                detection_cooldown = 1.5

        # OK 按钮
        if orange_in_bag > 0 and state != STATE_DONE:
            ok_button.handle_event(event)
            if ok_button.clicked:
                state = STATE_DONE
                ok_button.clicked = False
                # 爆炸庆祝粒子
                for _ in range(60):
                    p = BounceParticle(W//2, H//2)
                    p.vy = random.uniform(-12, -3)
                    p.vx = random.uniform(-10, 10)
                    p.color = random.choice([ORANGE, YELLOW, WHITE, GREEN])
                    p.r = random.randint(4, 12)
                    done_particles.append(p)

pygame.quit()
exit()