import pygame
import os
import cv2
import torch
import torchvision.transforms as transforms
from transformers import AutoModelForImageClassification
from PIL import Image  # kept for potential future use
import threading
import queue
import numpy as np
import math
import random
import time
import urllib.request
import json

# pyzbar 可选依赖：pip install pyzbar
try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    from pyzbar import pyzbar as _pyzbar_mod
    import ctypes, os as _os
    # 压制 zbar 内部 PDF417 断言 warning（写入 NUL）
    try:
        _zbar = ctypes.cdll.LoadLibrary(_pyzbar_mod.zbar.__file__)
        _zbar.zbar_set_verbosity(0)
    except Exception:
        pass
    # 重定向 stderr 到 NUL 仅在 pyzbar decode 期间（Windows 方案）
    import io, sys as _sys
    _DEVNULL = open(_os.devnull, 'w')
    PYZBAR_OK = True
except ImportError:
    PYZBAR_OK = False
    _DEVNULL  = None
    print("⚠  pyzbar 未安装，条码扫描不可用。运行: pip install pyzbar")

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
font_huge   = pygame.font.Font(None, 140)

# ── Sprites ──
SPRITE_PATH = r"C:\Users\hongy\Desktop\Frig\Free_pixel_food_16x16\Icons"
sprites = {}
for file in os.listdir(SPRITE_PATH):
    if file.endswith(".png"):
        name = file.replace(".png", "")
        img = pygame.image.load(os.path.join(SPRITE_PATH, file)).convert_alpha()
        sprites[name] = img

# 通用：找任意 sprite key（不区分大小写）
def find_sprite_key(keyword):
    for sk in sprites:
        if keyword.lower() in sk.lower():
            return sk
    return None

# 水果/蔬菜 label → sprite key 映射
LABEL_TO_SPRITE = {
    "apple": "apple", "banana": "banana", "carrot": "carrot",
    "cucumber": "cucumber", "eggplant": "eggplant", "garlic": "garlic",
    "grapes": "grapes", "kiwi": "kiwi", "lemon": "lemon",
    "mango": "mango", "onion": "onion", "orange": "orange",
    "pear": "pear", "pineapple": "pineapple", "potato": "potato",
    "strawberry": "strawberry", "tomato": "tomato", "watermelon": "watermelon",
    "corn": "corn", "peach": "peach", "cherry": "cherry",
    "ginger": "ginger", "cabbage": "cabbage",
    "bell pepper": "pepper", "capsicum": "pepper",
    "chilli pepper": "pepper", "jalapeno": "pepper",
    "pomegranate": "pomegranate",
}

def label_to_sprite(label):
    label_lower = label.lower().strip()
    if label_lower in LABEL_TO_SPRITE:
        k = LABEL_TO_SPRITE[label_lower]
        res = find_sprite_key(k)
        if res: return res
    for k, v in LABEL_TO_SPRITE.items():
        if k in label_lower:
            res = find_sprite_key(v)
            if res: return res
    return None

# ── Colors ──
PINK       = (255, 192, 203)
LIGHT_GRAY = (240, 240, 240)
DARK_GRAY  = (100, 100, 100)
BLACK      = (0,   0,   0  )
WHITE      = (255, 255, 255)
GREEN      = (50,  200, 50 )
RED        = (200, 50,  50 )
YELLOW     = (255, 200, 0  )
ORANGE_C   = (255, 140, 0  )
BAG_BROWN  = (139, 90,  43 )
BAG_DARK   = (100, 60,  20 )
BAG_LIGHT  = (180, 130, 70 )

# ── Bag params ──
BAG_X, BAG_Y = 820, 390
BAG_W, BAG_H = 160, 185

# ════════════════════════════════
#  物理动画类
# ════════════════════════════════

class FlyingFruit:
    """贝塞尔弧线飞入袋子"""
    def __init__(self, sprite_key, start_x, start_y, target_x, target_y):
        self.sprite_key = sprite_key
        self.x = float(start_x); self.y = float(start_y)
        self.t = 0.0; self.dur = 0.38   # ← 飞行时间缩短到0.38s，顺滑快速
        self.done = False
        self.angle = 0.0
        self.spin  = random.uniform(-10, 10)
        # 控制点：中间拱起
        self.p0 = (start_x, start_y)
        self.p1 = ((start_x + target_x)/2, min(start_y, target_y) - random.randint(60, 130))
        self.p2 = (target_x, target_y)
        self.trail = []

    def bezier(self, t):
        x = (1-t)**2*self.p0[0] + 2*(1-t)*t*self.p1[0] + t**2*self.p2[0]
        y = (1-t)**2*self.p0[1] + 2*(1-t)*t*self.p1[1] + t**2*self.p2[1]
        return x, y

    def update(self, dt):
        if self.done: return
        self.t = min(self.t + dt / self.dur, 1.0)
        self.angle += self.spin
        self.x, self.y = self.bezier(self.t)
        self.trail.append((self.x, self.y))
        if len(self.trail) > 10: self.trail.pop(0)
        if self.t >= 1.0: self.done = True

    def draw(self, surf):
        for i, (tx, ty) in enumerate(self.trail):
            alpha = int(160 * (i / max(len(self.trail), 1)))
            r = max(3, int(6 * (i / max(len(self.trail), 1))))
            ts = pygame.Surface((r*2, r*2), pygame.SRCALPHA)
            pygame.draw.circle(ts, (*ORANGE_C, alpha), (r, r), r)
            surf.blit(ts, (int(tx)-r, int(ty)-r))
        size = int(26 * (0.55 + 0.45 * self.t))
        if self.sprite_key in sprites:
            img = pygame.transform.scale(sprites[self.sprite_key], (size, size))
            img = pygame.transform.rotate(img, self.angle)
            surf.blit(img, img.get_rect(center=(int(self.x), int(self.y))))

class Particle:
    def __init__(self, x, y, explode=False):
        angle = random.uniform(-math.pi, 0) if not explode else random.uniform(0, math.tau)
        speed = random.uniform(2, 8) if not explode else random.uniform(3, 12)
        self.x = float(x); self.y = float(y)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.life = 1.0
        self.color = random.choice([ORANGE_C, YELLOW, (255,200,80),(255,100,0),WHITE,GREEN])
        self.r = random.randint(3, 9 if explode else 7)

    def update(self, dt):
        self.vy += 14 * dt
        self.x += self.vx; self.y += self.vy
        self.life -= dt * (2.2 if self.r < 6 else 1.8)

    def draw(self, surf):
        if self.life <= 0: return
        a = int(255 * max(0, self.life))
        s = pygame.Surface((self.r*2, self.r*2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.color, a), (self.r, self.r), self.r)
        surf.blit(s, (int(self.x)-self.r, int(self.y)-self.r))

class BagShake:
    def __init__(self): self.ox = 0.0; self.oy = 0.0; self.timer = 0.0
    def trigger(self): self.timer = 0.35
    def update(self, dt):
        if self.timer <= 0: self.ox = self.oy = 0.0; return
        self.timer -= dt
        d = self.timer / 0.35
        self.ox = math.sin(self.timer * 55) * 7 * d
        self.oy = math.sin(self.timer * 42) * 3 * d

def draw_bag(surf, shake, fruit_key, count):
    bx = BAG_X + shake.ox; by = BAG_Y + shake.oy
    # 袋体
    pts = [(bx-BAG_W//2+10,by),(bx+BAG_W//2-10,by),
           (bx+BAG_W//2-5, by+BAG_H),(bx-BAG_W//2+5, by+BAG_H)]
    pygame.draw.polygon(surf, BAG_BROWN, pts)
    pygame.draw.polygon(surf, BAG_DARK, pts, 3)
    # 折叠线
    for fy, a in [(by+28,2),(by+55,1)]:
        off = 15 + (fy-by)//8
        pygame.draw.line(surf, BAG_LIGHT, (bx-BAG_W//2+off,fy),(bx+BAG_W//2-off,fy), a)
    # 卷边
    rp = [(bx-BAG_W//2,by-12),(bx-BAG_W//2+10,by),(bx+BAG_W//2-10,by),(bx+BAG_W//2,by-12)]
    pygame.draw.polygon(surf, BAG_LIGHT, rp)
    pygame.draw.polygon(surf, BAG_DARK, rp, 2)
    # 底圆角
    pygame.draw.ellipse(surf, BAG_DARK, (bx-BAG_W//2+5, by+BAG_H-12, BAG_W-10, 20), 2)
    # 堆叠图标
    if fruit_key and fruit_key in sprites and count > 0:
        cols = 4; icon_sz = 20
        for i in range(min(count, 12)):
            ic = pygame.transform.scale(sprites[fruit_key], (icon_sz, icon_sz))
            ix = bx - BAG_W//2 + 22 + (i % cols) * 27
            iy = by + BAG_H - 28 - (i // cols) * 23
            surf.blit(ic, (int(ix), int(iy)))
    # 数量标
    if count > 0:
        ct = font_large.render(f"×{count}", True, WHITE)
        surf.blit(ct, (int(bx + BAG_W//2 - 14), int(by + BAG_H - 34)))

# ── Queue display ──
# shopping_queue: list of (sprite_key, count) tuples confirmed via OK
shopping_queue = []

def draw_queue(surf, fruit_key, bag_cnt, queue_list):
    """Bottom strip: confirmed queue items (sprite icon + count + optional name label)"""
    qx, qy = 50, 618
    surf.blit(font_medium.render("队列:", True, BLACK), (qx, qy))
    if queue_list:
        ix = qx + 55
        for entry in queue_list:
            sk  = entry[0]
            cnt = entry[1]
            lbl = entry[2] if len(entry) > 2 else ""
            if sk and sk in sprites:
                icon = pygame.transform.scale(sprites[sk], (36, 36))
                surf.blit(icon, (ix, qy - 4))
            ct = font_medium.render(f"×{cnt}", True, ORANGE_C)
            surf.blit(ct, (ix + 38, qy + 8))
            # 如果有商品名（条码商品），显示小字名称
            if lbl and lbl != sk:
                short = lbl[:10] + "…" if len(lbl) > 10 else lbl
                ls = font_small.render(short, True, DARK_GRAY)
                surf.blit(ls, (ix, qy - 18))
            ix += 100
    else:
        surf.blit(font_medium.render("—", True, DARK_GRAY), (qx + 55, qy))

# ── OK button ──
class OKButton:
    def __init__(self):
        self.rect = pygame.Rect(1010, 560, 140, 65)
        self.hovered = False; self.clicked = False; self.pulse = 0.0
    def update(self, dt, mp):
        self.hovered = self.rect.collidepoint(mp); self.pulse += dt * 3
    def draw(self, surf):
        scale = 1.0 + 0.04 * math.sin(self.pulse)
        w, h = int(self.rect.width*scale), int(self.rect.height*scale)
        r = pygame.Rect(self.rect.centerx-w//2, self.rect.centery-h//2, w, h)
        pygame.draw.rect(surf, (30,180,30) if self.hovered else (50,160,50), r, border_radius=12)
        pygame.draw.rect(surf, (20,120,20), r, 3, border_radius=12)
        lbl = font_large.render("✓  OK", True, WHITE)
        surf.blit(lbl, lbl.get_rect(center=r.center))
    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and self.rect.collidepoint(event.pos):
            self.clicked = True

# ════════════════════════════════
#  摄像头线程
# ════════════════════════════════
cv_queue = queue.Queue()
CAM_W, CAM_H = 320, 240

def camera_thread():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened(): print("无法打开摄像头"); return
    while True:
        ret, frame = cap.read()
        if ret:
            if cv_queue.qsize() >= 2: cv_queue.get()
            cv_queue.put(frame)

threading.Thread(target=camera_thread, daemon=True).start()

# ════════════════════════════════
#  模型加载 — 推理加速优化
# ════════════════════════════════
print("加载模型...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

hf_model = AutoModelForImageClassification.from_pretrained(
    "jazzmacedo/fruits-and-vegetables-detector-36"
)
hf_model.to(device)
hf_model.eval()

# torch.compile 在 Windows 上需要 MSVC (cl.exe)，直接跳过

# ── half precision 加速（CUDA 可用时用 fp16，约快 40%）──
if device.type == "cuda":
    hf_model = hf_model.half()
    print("✓ FP16 推理已启用 (CUDA)")

HF_LABELS = list(hf_model.config.id2label.values())

# ── 预处理：160px 降低推理时间 ──
INFER_SIZE = 160
_normalize = transforms.Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])
_to_tensor  = transforms.ToTensor()

# 预热：消除第一次推理冷启动（捕获所有异常）
print("预热模型...")
try:
    dummy = torch.zeros(1, 3, INFER_SIZE, INFER_SIZE).to(device)
    if device.type == "cuda": dummy = dummy.half()
    with torch.no_grad():
        for _ in range(3):
            hf_model(dummy)
    print("✓ 预热完成")
except Exception as e:
    print(f"预热跳过: {e}")

def classify_frame(frame_bgr):
    # cv2 直接 resize，比 PIL.Resize 快
    small = cv2.resize(frame_bgr, (INFER_SIZE, INFER_SIZE))
    rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    tensor = _normalize(_to_tensor(rgb)).unsqueeze(0).to(device)
    if device.type == "cuda": tensor = tensor.half()
    with torch.no_grad():
        probs = torch.softmax(hf_model(tensor).logits.float(), dim=1)
        conf, idx = torch.max(probs, dim=1)
    return HF_LABELS[idx.item()], conf.item()

# ════════════════════════════════
#  推理线程 — 提高采样频率
# ════════════════════════════════
detect_queue = queue.Queue(maxsize=1)
CONF_THRESH  = 0.60

def detection_thread():
    while True:
        if not cv_queue.empty():
            frame = list(cv_queue.queue)[-1]
            label, conf = classify_frame(frame)
            if conf >= CONF_THRESH:
                if detect_queue.full():
                    try: detect_queue.get_nowait()
                    except: pass
                detect_queue.put((label, conf))
        time.sleep(0.08)   # ← 从 0.15 提高到 0.08，~12fps 推理

threading.Thread(target=detection_thread, daemon=True).start()

# ── 条码检测线程 ──
# 独立线程持续扫帧，结果放进 barcode_raw_queue
barcode_raw_queue = queue.Queue(maxsize=2)   # (code_str, rect_list)
_bc_scan_active   = threading.Event()        # set = 条码模式开启

def _suppress_stderr_decode(gray):
    """调用 pyzbar，压制 C 层 stderr warning"""
    import os as _os
    old_fd = _os.dup(2)
    try:
        nul = _os.open(_os.devnull, _os.O_WRONLY)
        _os.dup2(nul, 2); _os.close(nul)
        return pyzbar_decode(gray)
    finally:
        _os.dup2(old_fd, 2); _os.close(old_fd)

def barcode_scan_thread():
    last_code = ""
    while True:
        _bc_scan_active.wait()          # 等待条码模式激活
        if cv_queue.empty():
            time.sleep(0.05)
            continue
        frame = list(cv_queue.queue)[-1]   # 取最新帧，不消费队列

        if not PYZBAR_OK:
            time.sleep(0.1); continue

        # 多尺度：原图 + 放大，提高识别率
        results = []
        for scale in (1.0, 1.5):
            if scale == 1.0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                h, w = frame.shape[:2]
                big  = cv2.resize(frame, (int(w*scale), int(h*scale)))
                gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
            # 对比度增强
            gray = cv2.equalizeHist(gray)
            decoded = _suppress_stderr_decode(gray)
            if decoded:
                results = decoded
                break

        if results:
            rects = []
            for bc in results:
                code = bc.data.decode("utf-8", errors="replace").strip()
                r    = bc.rect
                rects.append((r.left, r.top, r.width, r.height))
                if code and code != last_code:
                    last_code = code
                    if barcode_raw_queue.full():
                        try: barcode_raw_queue.get_nowait()
                        except: pass
                    barcode_raw_queue.put((code, rects))
                    break
        else:
            last_code = ""   # 条码离开镜头后重置，下次能重扫

        time.sleep(0.08)

threading.Thread(target=barcode_scan_thread, daemon=True).start()

# ════════════════════════════════
#  状态机
# ════════════════════════════════
# IDLE       → 等待识别
# ASK        → 检测到食物，显示"1个 / 多个？"确认框
# BAGGING    → 用户选了数量，可以点击袋子添加
# DONE       → 按了OK，展示结果

STATE_IDLE    = "idle"
STATE_ASK     = "ask"
STATE_BAGGING = "bagging"
STATE_DONE    = "done"
STATE_BARCODE = "barcode"   # 条码扫描模式

state = STATE_IDLE

# ── 条码扫描相关 ──
barcode_result_queue  = queue.Queue(maxsize=1)
barcode_last_scan     = ""
barcode_cooldown      = 0.0
barcode_overlay_rects = []   # [(x,y,w,h), ...]
barcode_lookup_busy   = False

def lookup_barcode(code_str):
    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{code_str}.json"
        req = __import__("urllib.request", fromlist=["Request", "urlopen"]).Request(
            url, headers={"User-Agent": "FridgeBud/1.0"})
        import urllib.request as _ur
        with _ur.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        if data.get("status") == 1:
            p = data.get("product", {})
            name = (p.get("product_name_zh") or p.get("product_name_en")
                    or p.get("product_name") or "").strip()
            return name if name else None
    except Exception:
        pass
    return None

def barcode_lookup_thread(code_str):
    global barcode_lookup_busy
    name = lookup_barcode(code_str)
    item = (code_str, name or code_str)
    if barcode_result_queue.full():
        try: barcode_result_queue.get_nowait()
        except: pass
    barcode_result_queue.put(item)
    barcode_lookup_busy = False

class BarcodeDialog:
    def __init__(self, code, name):
        self.code   = code
        self.name   = name
        self.count  = 1
        self.choice = None
        self.btn_add   = pygame.Rect(630, 460, 160, 52)
        self.btn_skip  = pygame.Rect(810, 460, 140, 52)
        self.btn_plus  = pygame.Rect(790, 395, 44, 44)
        self.btn_minus = pygame.Rect(630, 395, 44, 44)

    def update(self, dt): pass

    def draw(self, surf, mp):
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 110))
        surf.blit(ov, (0, 0))

        box = pygame.Rect(590, 290, 440, 265)
        pygame.draw.rect(surf, WHITE, box, border_radius=18)
        pygame.draw.rect(surf, (50, 120, 220), box, 3, border_radius=18)

        # 标题
        title = font_large.render("条码商品", True, (50, 120, 220))
        surf.blit(title, title.get_rect(centerx=box.centerx, top=box.y + 14))

        # 商品名
        disp_name = self.name if len(self.name) <= 24 else self.name[:22] + "…"
        ns = font_large.render(disp_name, True, BLACK)
        surf.blit(ns, ns.get_rect(centerx=box.centerx, top=box.y + 54))

        cs = font_small.render(f"条码: {self.code}", True, DARK_GRAY)
        surf.blit(cs, cs.get_rect(centerx=box.centerx, top=box.y + 88))

        # 数量行
        ql = font_medium.render("数量:", True, BLACK)
        surf.blit(ql, (box.x + 30, box.y + 138))

        mc = (170,170,170) if self.btn_minus.collidepoint(mp) else (200,200,200)
        pc = (170,170,170) if self.btn_plus.collidepoint(mp)  else (200,200,200)
        pygame.draw.rect(surf, mc, self.btn_minus, border_radius=8)
        pygame.draw.rect(surf, pc, self.btn_plus,  border_radius=8)
        ms = font_large.render("−", True, BLACK)
        ps = font_large.render("+", True, BLACK)
        surf.blit(ms, ms.get_rect(center=self.btn_minus.center))
        surf.blit(ps, ps.get_rect(center=self.btn_plus.center))

        cnt_s = font_xl.render(str(self.count), True, ORANGE_C)
        surf.blit(cnt_s, cnt_s.get_rect(centerx=box.centerx, centery=self.btn_plus.centery))

        # 按钮
        ca = (30,150,30) if self.btn_add.collidepoint(mp) else GREEN
        pygame.draw.rect(surf, ca, self.btn_add, border_radius=12)
        at = font_large.render("加入队列", True, WHITE)
        surf.blit(at, at.get_rect(center=self.btn_add.center))

        csk = (210,40,40) if self.btn_skip.collidepoint(mp) else RED
        pygame.draw.rect(surf, csk, self.btn_skip, border_radius=12)
        st = font_medium.render("✕ 跳过", True, WHITE)
        surf.blit(st, st.get_rect(center=self.btn_skip.center))

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.btn_add.collidepoint(event.pos):   self.choice = "add"
            if self.btn_skip.collidepoint(event.pos):  self.choice = "skip"
            if self.btn_plus.collidepoint(event.pos):  self.count = min(99, self.count + 1)
            if self.btn_minus.collidepoint(event.pos): self.count = max(1,  self.count - 1)

barcode_dialog = None

# ── 模式切换按钮（右上角）──
MODE_BTN = pygame.Rect(W - 200, 14, 185, 38)
def draw_mode_btn(surf, mp):
    """画右上角模式切换按钮"""
    is_bc = state == STATE_BARCODE
    col   = (50, 120, 220) if is_bc else (80, 80, 80)
    hov   = MODE_BTN.collidepoint(mp)
    if hov: col = tuple(min(255, c+30) for c in col)
    pygame.draw.rect(surf, col, MODE_BTN, border_radius=10)
    label = "📸 摄像头识别" if is_bc else "🔲 扫条码"
    ls = font_medium.render(label, True, WHITE)
    surf.blit(ls, ls.get_rect(center=MODE_BTN.center))

# 当前水果
cur_label      = ""
cur_sprite     = None
cur_conf       = 0.0
# 上次识别显示（即使在 BAGGING 状态也显示）
last_label_disp = ""
last_conf_disp  = 0.0

# 袋子
bag_count    = 0
bag_sprite   = None   # 当前袋子里装的是什么水果

# 已确认的购物队列（多次 OK 可累积）
shopping_queue = []

# 动画
flying      = []
particles   = []
bag_shake   = BagShake()
ok_button   = OKButton()
done_parts  = []

# 冷却：防止 BAGGING 时推理结果覆盖当前水果
detect_cooldown = 0.0

# 连续点击计时器（快速多次点击时自动排队飞出）
click_pending  = 0     # 还有多少个待飞的果子
click_timer    = 0.0   # 距离下一个飞出的时间
CLICK_INTERVAL = 0.18  # 每隔 0.18s 飞一个，比原来快 3x

# ════════════════════════════════
#  ASK 界面：1个 / 多个
# ════════════════════════════════
class AskDialog:
    """识别到食物后弹出的"几个？"对话框"""
    def __init__(self, label, sprite_key, conf):
        self.label      = label
        self.sprite_key = sprite_key
        self.conf       = conf
        self.btn_one  = pygame.Rect(640, 440, 160, 56)
        self.btn_many = pygame.Rect(820, 440, 160, 56)
        self.btn_skip = pygame.Rect(730, 510, 130, 40)
        self.choice   = None   # 1 / "many" / "skip"
        self.pulse    = 0.0

    def update(self, dt):
        self.pulse += dt * 4

    def draw(self, surf, mp):
        # 半透明遮罩
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 110))
        surf.blit(ov, (0, 0))

        # 对话框背景
        box = pygame.Rect(590, 300, 420, 280)
        pygame.draw.rect(surf, WHITE, box, border_radius=18)
        pygame.draw.rect(surf, ORANGE_C, box, 3, border_radius=18)

        # 图标
        if self.sprite_key in sprites:
            icon = pygame.transform.scale(sprites[self.sprite_key], (56, 56))
            surf.blit(icon, (box.centerx - 28, box.y + 18))

        # 标题
        name_surf = font_large.render(self.label.replace("_"," ").title(), True, BLACK)
        surf.blit(name_surf, name_surf.get_rect(centerx=box.centerx, top=box.y+82))

        conf_surf = font_medium.render(f"置信度 {self.conf:.0%}", True, DARK_GRAY)
        surf.blit(conf_surf, conf_surf.get_rect(centerx=box.centerx, top=box.y+114))

        q_surf = font_large.render("加几个？", True, BLACK)
        surf.blit(q_surf, q_surf.get_rect(centerx=box.centerx, top=box.y+148))

        # 按钮 "1个"
        c1 = (40,190,40) if self.btn_one.collidepoint(mp) else GREEN
        pygame.draw.rect(surf, c1, self.btn_one, border_radius=12)
        pygame.draw.rect(surf, (20,120,20), self.btn_one, 2, border_radius=12)
        t1 = font_large.render("1 个", True, WHITE)
        surf.blit(t1, t1.get_rect(center=self.btn_one.center))

        # 按钮 "多个"
        cm = (220,120,20) if self.btn_many.collidepoint(mp) else (255,160,30)
        pygame.draw.rect(surf, cm, self.btn_many, border_radius=12)
        pygame.draw.rect(surf, (180,90,0), self.btn_many, 2, border_radius=12)
        tm = font_large.render("多 个", True, WHITE)
        surf.blit(tm, tm.get_rect(center=self.btn_many.center))

        # 跳过
        cs = RED if self.btn_skip.collidepoint(mp) else (160,50,50)
        pygame.draw.rect(surf, cs, self.btn_skip, border_radius=8)
        ts = font_medium.render("✕ 跳过", True, WHITE)
        surf.blit(ts, ts.get_rect(center=self.btn_skip.center))

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.btn_one.collidepoint(event.pos):  self.choice = 1
            if self.btn_many.collidepoint(event.pos): self.choice = "many"
            if self.btn_skip.collidepoint(event.pos): self.choice = "skip"

ask_dialog = None

# ════════════════════════════════
#  主循环
# ════════════════════════════════
running = True
dt = 0.0
cam_frame_latest = None

while running:
    dt = clock.tick(60) / 1000.0
    mp = pygame.mouse.get_pos()

    # ── 拉取摄像头帧 ──
    if not cv_queue.empty():
        cam_frame_latest = cv_queue.get()

    # ── 条码模式：控制扫描线程开关 ──
    if state == STATE_BARCODE:
        _bc_scan_active.set()
    else:
        _bc_scan_active.clear()

    # 拉取扫描线程的原始结果，触发商品名查询
    if state == STATE_BARCODE and barcode_dialog is None and barcode_cooldown <= 0:
        if not barcode_raw_queue.empty():
            raw_code, raw_rects = barcode_raw_queue.get()
            barcode_overlay_rects.clear()
            barcode_overlay_rects.extend(raw_rects)
            if not barcode_lookup_busy:
                barcode_lookup_busy = True
                barcode_cooldown    = 2.5
                threading.Thread(target=barcode_lookup_thread,
                                 args=(raw_code,), daemon=True).start()

    if barcode_cooldown > 0:
        barcode_cooldown -= dt

    # 拉取商品名查询结果，弹出确认框
    if not barcode_result_queue.empty() and barcode_dialog is None:
        code, name = barcode_result_queue.get()
        barcode_dialog = BarcodeDialog(code, name)
        barcode_overlay_rects.clear()

    # 更新条码对话框
    if barcode_dialog:
        barcode_dialog.update(dt)

    # ── 拉取推理结果（只在 IDLE 状态接受） ──
    if state == STATE_IDLE and detect_cooldown <= 0:
        if not detect_queue.empty():
            lbl, conf = detect_queue.get()
            skey = label_to_sprite(lbl)
            last_label_disp = lbl; last_conf_disp = conf
            if skey:
                cur_label = lbl; cur_sprite = skey; cur_conf = conf
                ask_dialog = AskDialog(lbl, skey, conf)
                state = STATE_ASK
                detect_cooldown = 0.0

    if detect_cooldown > 0:
        detect_cooldown -= dt

    # ── 更新动画 ──
    for fo in flying[:]:
        fo.update(dt)
        if fo.done:
            flying.remove(fo)
            for _ in range(14):
                particles.append(Particle(BAG_X, BAG_Y + 5))
            bag_shake.trigger()

    for p in particles[:]:
        p.update(dt); 
        if p.life <= 0: particles.remove(p)
    for p in done_parts[:]:
        p.update(dt)
        if p.life <= 0: done_parts.remove(p)

    bag_shake.update(dt)
    ok_button.update(dt, mp)
    if ask_dialog: ask_dialog.update(dt)

    # ── 连续点击自动飞出 ──
    if click_pending > 0:
        click_timer -= dt
        if click_timer <= 0:
            start_x = 380 + random.randint(-20, 20)
            start_y = 180 + random.randint(-25, 25)
            flying.append(FlyingFruit(cur_sprite, start_x, start_y, BAG_X, BAG_Y + 8))
            bag_count += 1
            click_pending -= 1
            click_timer = CLICK_INTERVAL

    # ════ 绘制 ════
    screen.fill(PINK)

    # 摄像头预览
    screen.blit(font_medium.render("摄像头识别", True, BLACK), (50, 20))
    if cam_frame_latest is not None:
        disp = cv2.cvtColor(cv2.resize(cam_frame_latest,(CAM_W,CAM_H)), cv2.COLOR_BGR2RGB)
        cam_surf = pygame.surfarray.make_surface(np.flipud(np.rot90(disp)))
        screen.blit(cam_surf, (50, 52))

    # 条码模式覆盖：在摄像头画面上画检测框
    if state == STATE_BARCODE and cam_frame_latest is not None:
        # 画"正在扫描"提示
        bc_hint = font_medium.render(
            "🔲 对准条码..." if not barcode_lookup_busy else "⏳ 查询中...",
            True, (50, 120, 220))
        screen.blit(bc_hint, (50, 308))
        # 画条码框（摄像头画面坐标系映射）
        for (bx, by, bw, bh) in barcode_overlay_rects:
            sx = int(bx * CAM_W / cam_frame_latest.shape[1]) + 50
            sy = int(by * CAM_H / cam_frame_latest.shape[0]) + 52
            sw = int(bw * CAM_W / cam_frame_latest.shape[1])
            sh = int(bh * CAM_H / cam_frame_latest.shape[0])
            pygame.draw.rect(screen, (50, 220, 50), (sx, sy, sw, sh), 3)

    # 右上角模式按钮
    draw_mode_btn(screen, mp)

    # 识别标签
    if last_label_disp:
        col = GREEN if last_conf_disp > 0.75 else YELLOW
        screen.blit(font_small.render(f"识别: {last_label_disp}  ({last_conf_disp:.0%})", True, BLACK), (50, 308))

    # IDLE 提示
    if state == STATE_IDLE:
        hint = font_medium.render("把食物对准摄像头...", True, DARK_GRAY)
        screen.blit(hint, (50, 338))

    # 袋子标题（BAGGING 以后才显示）
    if state in (STATE_BAGGING, STATE_DONE) or bag_count > 0:
        screen.blit(font_medium.render("购物袋", True, BLACK), (BAG_X - 30, BAG_Y - 35))
        draw_bag(screen, bag_shake, bag_sprite, bag_count)

    # 飞行动画
    for fo in flying: fo.draw(screen)
    for p in particles: p.draw(screen)

    # 队列底栏（始终显示）
    draw_queue(screen, bag_sprite, bag_count, shopping_queue)

    # BAGGING：袋子高亮 + 提示
    if state == STATE_BAGGING:
        brect = pygame.Rect(BAG_X-BAG_W//2-12, BAG_Y-25, BAG_W+24, BAG_H+38)
        pw = int(3 + 2*math.sin(time.time()*8))
        pygame.draw.rect(screen, ORANGE_C, brect, pw, border_radius=8)
        arr_y = int(BAG_Y - 46 + 5*math.sin(time.time()*5))
        at = font_large.render("▼ 点击添加", True, ORANGE_C)
        screen.blit(at, at.get_rect(centerx=BAG_X, top=arr_y))

    # OK 按钮 — 有东西就显示（DONE 时变"继续"，由下方 DONE block 单独绘制）
    if bag_count > 0 and state != STATE_DONE:
        ok_button.draw(screen)
        screen.blit(font_small.render("完成 / 随时退出", True, DARK_GRAY),
                    (ok_button.rect.centerx - 42, ok_button.rect.bottom + 4))

    # ASK 对话框（覆盖在最上层）
    if state == STATE_ASK and ask_dialog:
        ask_dialog.draw(screen, mp)

    # 条码对话框（最上层）
    if barcode_dialog:
        barcode_dialog.draw(screen, mp)

    # DONE：粒子 + 顶部提示条，不遮住正常 UI
    if state == STATE_DONE:
        for p in done_parts: p.draw(screen)
        # 顶部庆祝横幅
        banner = pygame.Surface((W, 64), pygame.SRCALPHA)
        banner.fill((30, 160, 30, 210))
        screen.blit(banner, (0, 0))
        # 水果图标 + 数量
        bx_off = W // 2 - 80
        if bag_sprite and bag_sprite in sprites:
            big = pygame.transform.scale(sprites[bag_sprite], (44, 44))
            screen.blit(big, (bx_off, 10))
            bx_off += 52
        ct_surf = font_xl.render(f"×{bag_count}  已加入队列！", True, WHITE)
        screen.blit(ct_surf, ct_surf.get_rect(midleft=(bx_off, 32)))
        # 继续提示
        cont = font_small.render("点击 OK 继续添加  |  ESC 退出", True, (200, 255, 200))
        screen.blit(cont, cont.get_rect(centerx=W//2, top=H - 22))

        # OK 按钮变成"继续"
        ok_button.draw(screen)
        screen.blit(font_small.render("继续添加", True, DARK_GRAY),
                    (ok_button.rect.centerx - 30, ok_button.rect.bottom + 4))

    pygame.display.update()

    # ════ 事件 ════
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif state == STATE_DONE:
                # ESC已处理，其他键不做操作（用OK按钮继续）
                pass

        # 模式切换按钮
        if event.type == pygame.MOUSEBUTTONDOWN:
            if MODE_BTN.collidepoint(event.pos):
                if state == STATE_BARCODE:
                    state = STATE_IDLE
                    barcode_overlay_rects.clear()
                    barcode_dialog   = None
                    barcode_cooldown = 0.0
                    _bc_scan_active.clear()
                    # 清空队列防止残留
                    while not barcode_raw_queue.empty():
                        try: barcode_raw_queue.get_nowait()
                        except: pass
                elif state == STATE_IDLE:
                    state = STATE_BARCODE
                    barcode_cooldown = 0.0
                    _bc_scan_active.set()

        # 条码对话框事件
        if barcode_dialog:
            barcode_dialog.handle(event)
            if barcode_dialog.choice == "add":
                # 加入购物队列（用通用包装box sprite，或查找最接近的sprite）
                bname_lower = barcode_dialog.name.lower()
                bsprite = None
                for kw in bname_lower.split():
                    bsprite = find_sprite_key(kw)
                    if bsprite: break
                if not bsprite:
                    bsprite = find_sprite_key("box") or find_sprite_key("bag") or list(sprites.keys())[0]
                bcount = barcode_dialog.count
                bcode  = barcode_dialog.code
                bname  = barcode_dialog.name
                # 加入 shopping_queue（用 (sprite, count, label) 扩展格式，旧代码兼容2-tuple）
                merged = False
                for i, entry in enumerate(shopping_queue):
                    sk = entry[0]; cnt = entry[1]
                    lbl = entry[2] if len(entry) > 2 else ""
                    if lbl == bname or sk == bsprite and lbl == bname:
                        shopping_queue[i] = (sk, cnt + bcount, lbl)
                        merged = True; break
                if not merged:
                    shopping_queue.append((bsprite, bcount, bname))
                barcode_dialog = None
                barcode_last_scan = ""
                barcode_cooldown  = 1.0
            elif barcode_dialog.choice == "skip":
                barcode_dialog    = None
                barcode_last_scan = ""
                barcode_cooldown  = 1.0

        # ASK 对话框事件
        if state == STATE_ASK and ask_dialog:
            ask_dialog.handle(event)
            if ask_dialog.choice == 1:
                # 立刻飞 1 个
                bag_sprite = cur_sprite
                flying.append(FlyingFruit(cur_sprite, 380, 180, BAG_X, BAG_Y+8))
                bag_count += 1
                state = STATE_BAGGING
                ask_dialog = None; detect_cooldown = 1.2
            elif ask_dialog.choice == "many":
                # 进入 BAGGING 模式，每次点击 +1
                bag_sprite = cur_sprite
                state = STATE_BAGGING
                ask_dialog = None; detect_cooldown = 1.2
            elif ask_dialog.choice == "skip":
                state = STATE_IDLE
                ask_dialog = None; detect_cooldown = 1.5

        # BAGGING：点击袋子区域
        if state == STATE_BAGGING and event.type == pygame.MOUSEBUTTONDOWN:
            brect = pygame.Rect(BAG_X-BAG_W//2-15, BAG_Y-30, BAG_W+30, BAG_H+45)
            if brect.collidepoint(event.pos):
                # 直接飞一个（无延迟）；如果上一个还在飞，排队延迟出发
                if not flying:
                    flying.append(FlyingFruit(cur_sprite,
                        380+random.randint(-20,20), 180+random.randint(-25,25),
                        BAG_X, BAG_Y+8))
                    bag_count += 1
                else:
                    # 在当前飞行结束后快速跟上
                    click_pending += 1
                    if click_timer <= 0:
                        click_timer = CLICK_INTERVAL

        # OK 按钮
        ok_button.handle(event)
        if ok_button.clicked:
            ok_button.clicked = False
            if state == STATE_DONE:
                # "继续"：把当前袋子存入队列，重置袋子，回到 IDLE
                merged = False
                for i, entry in enumerate(shopping_queue):
                    if entry[0] == bag_sprite and (len(entry) < 3 or entry[2] == ""):
                        shopping_queue[i] = (entry[0], entry[1] + bag_count, "")
                        merged = True; break
                if not merged:
                    shopping_queue.append((bag_sprite, bag_count, ""))
                bag_count = 0; bag_sprite = None
                flying.clear(); particles.clear(); done_parts.clear()
                click_pending = 0; detect_cooldown = 1.0
                state = STATE_IDLE
            elif bag_count > 0:
                # 第一次按 OK：确认入队列，进 DONE 状态
                state = STATE_DONE
                click_pending = 0
                for _ in range(65):
                    p = Particle(W//2, H//2, explode=True)
                    done_parts.append(p)

pygame.quit()
exit()