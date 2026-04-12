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
import urllib.request
import json
import datetime
import heapq

# pyzbar 可选依赖
try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    from pyzbar import pyzbar as _pyzbar_mod
    import ctypes, os as _os
    try:
        _zbar = ctypes.cdll.LoadLibrary(_pyzbar_mod.zbar.__file__)
        _zbar.zbar_set_verbosity(0)
    except Exception:
        pass
    import io, sys as _sys
    _DEVNULL = open(_os.devnull, 'w')
    PYZBAR_OK = True
except ImportError:
    PYZBAR_OK = False
    _DEVNULL  = None
    print("[WARN] pyzbar not installed. pip install pyzbar")

pygame.init()
W, H = 1200, 700
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("FridgeBud ✨")
clock = pygame.time.Clock()

# ════════════════════════════════
#  中文字体加载（解决方框问题）
# ════════════════════════════════
# 按优先级尝试加载 Windows 中文字体
_CN_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",     # 微软雅黑粗
    r"C:\Windows\Fonts\simhei.ttf",     # 黑体
    r"C:\Windows\Fonts\simsun.ttc",     # 宋体
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    # Linux
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
]

_cn_font_path = None
for fp in _CN_FONT_CANDIDATES:
    if os.path.exists(fp):
        _cn_font_path = fp
        print(f"[Font] Using: {fp}")
        break

if _cn_font_path is None:
    print("[Font] WARNING: No CJK font found, falling back to default (may show boxes)")

def make_font(size):
    """创建支持中文的字体"""
    if _cn_font_path:
        try:
            return pygame.font.Font(_cn_font_path, size)
        except Exception:
            pass
    return pygame.font.Font(None, size)

font_huge   = make_font(70)
font_xl     = make_font(48)
font_large  = make_font(26)
font_medium = make_font(20)
font_small  = make_font(16)
font_tiny   = make_font(13)

# ── Sprites ──
SPRITE_PATH = r"C:\Users\hongy\Desktop\Frig\Free_pixel_food_16x16\Icons"
sprites = {}
if os.path.isdir(SPRITE_PATH):
    for file in os.listdir(SPRITE_PATH):
        if file.endswith(".png"):
            name = file.replace(".png", "")
            img = pygame.image.load(os.path.join(SPRITE_PATH, file)).convert_alpha()
            sprites[name] = img

def find_sprite_key(keyword):
    for sk in sprites:
        if keyword.lower() in sk.lower():
            return sk
    return None

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
        res = find_sprite_key(LABEL_TO_SPRITE[label_lower])
        if res: return res
    for k, v in LABEL_TO_SPRITE.items():
        if k in label_lower:
            res = find_sprite_key(v)
            if res: return res
    return None

# ═══════════════════════════════════
#  食物分类 & 保质期默认天数
# ═══════════════════════════════════
CATEGORY_MAP = {
    "apple": "fruit", "banana": "fruit", "grapes": "fruit", "kiwi": "fruit",
    "lemon": "fruit", "mango": "fruit", "orange": "fruit", "pear": "fruit",
    "pineapple": "fruit", "strawberry": "fruit", "watermelon": "fruit",
    "peach": "fruit", "cherry": "fruit", "pomegranate": "fruit",
    "carrot": "veggie", "cucumber": "veggie", "eggplant": "veggie",
    "garlic": "veggie", "onion": "veggie", "potato": "veggie",
    "tomato": "veggie", "corn": "veggie", "ginger": "veggie",
    "cabbage": "veggie", "bell pepper": "veggie", "capsicum": "veggie",
    "chilli pepper": "veggie", "jalapeno": "veggie",
}

DEFAULT_EXPIRY_DAYS = {
    "apple": 14, "banana": 5, "grapes": 7, "kiwi": 10,
    "lemon": 21, "mango": 5, "orange": 14, "pear": 7,
    "pineapple": 5, "strawberry": 3, "watermelon": 7,
    "peach": 5, "cherry": 4, "pomegranate": 14,
    "carrot": 21, "cucumber": 7, "eggplant": 7,
    "garlic": 30, "onion": 30, "potato": 21,
    "tomato": 7, "corn": 5, "ginger": 21,
    "cabbage": 14, "bell pepper": 10, "capsicum": 10,
    "chilli pepper": 14, "jalapeno": 14,
}

# ═══════════════════════════════════
#  OpenAI API — 估算过期日期
# ═══════════════════════════════════
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
FRIDGE_TEMP_C  = 8

def estimate_shelf_life_openai(food_name, callback):
    try:
        prompt = (
            f"You are a food safety expert. "
            f"Estimate how many days '{food_name}' (fresh, uncut, store-bought) "
            f"can be safely stored in a refrigerator at {FRIDGE_TEMP_C} C before it spoils. "
            f"Respond ONLY in valid JSON: {{\"days\": <int>, \"explanation\": \"<one sentence>\"}}\n"
            f"No markdown, no extra text."
        )
        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 120, "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {OPENAI_API_KEY}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"].strip()
        if text.startswith("```"): text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):   text = text[:-3]
        result = json.loads(text.strip())
        callback(food_name, int(result.get("days", 7)), result.get("explanation", ""))
    except Exception as e:
        print(f"[OpenAI] fail ({food_name}): {e}")
        d, ex = _local_shelf_life(food_name)
        callback(food_name, d, ex)

_LOCAL_SHELF = {
    "apple": (28, "Apples keep ~4 weeks refrigerated."),
    "banana": (5, "Bananas brown quickly at 8C."),
    "carrot": (21, "Carrots stay crisp ~3 weeks."),
    "cucumber": (7, "Chill-sensitive; ~1 week at 8C."),
    "eggplant": (7, "~1 week refrigerated."),
    "garlic": (60, "Whole garlic ~2 months."),
    "grapes": (10, "~10 days in fridge."),
    "kiwi": (21, "Ripe kiwi ~3 weeks."),
    "lemon": (21, "~3 weeks."),
    "mango": (7, "Ripe mango ~5-7 days."),
    "onion": (30, "~1 month."),
    "orange": (21, "~3 weeks."),
    "pear": (10, "~10 days."),
    "pineapple": (5, "~5 days cut."),
    "potato": (21, "~2-3 weeks at 8C."),
    "strawberry": (5, "Very perishable; ~5 days."),
    "tomato": (7, "~1 week; flavor degrades."),
    "watermelon": (7, "Cut ~5-7 days."),
    "corn": (5, "Loses sweetness fast."),
    "peach": (5, "~5 days."), "cherry": (7, "~1 week."),
    "ginger": (21, "~3 weeks."), "cabbage": (14, "~2 weeks."),
    "bell pepper": (10, "~10 days."), "pomegranate": (30, "~1 month."),
}

def _local_shelf_life(food_name):
    key = food_name.lower().strip()
    if key in _LOCAL_SHELF: return _LOCAL_SHELF[key]
    for k, v in _LOCAL_SHELF.items():
        if k in key or key in k: return v
    return (7, f"Default ~7 days at {FRIDGE_TEMP_C}C.")

# ═══════════════════════════════════
#  Priority Queue（按过期日期排序）
# ═══════════════════════════════════
class FridgePriorityQueue:
    def __init__(self):
        self._heap = []
        self._counter = 0

    def push(self, item_dict):
        self._counter += 1
        heapq.heappush(self._heap, (item_dict["expiry_date"], self._counter, item_dict))

    def pop(self):
        return heapq.heappop(self._heap)[2] if self._heap else None

    def peek(self):
        return self._heap[0][2] if self._heap else None

    def remove_by_name(self, name):
        for i, (_, _, item) in enumerate(self._heap):
            if item["name"] == name:
                self._heap.pop(i); heapq.heapify(self._heap); return item
        return None

    def all_items(self):
        return [item for (_, _, item) in sorted(self._heap)]

    def __len__(self): return len(self._heap)
    def __bool__(self): return len(self._heap) > 0

fridge_pq = FridgePriorityQueue()
_shelf_result_queue = queue.Queue()
_pending_shelf = {}

def add_to_fridge_pq(name, sprite_key, count, barcode=""):
    pending_key = f"{name}_{time.time()}"
    _pending_shelf[pending_key] = {
        "name": name, "sprite_key": sprite_key, "count": count,
        "barcode": barcode, "added_date": datetime.datetime.now(),
    }
    def _cb(food_name, days, explanation):
        _shelf_result_queue.put((pending_key, days, explanation))
    threading.Thread(target=estimate_shelf_life_openai, args=(name, _cb), daemon=True).start()

def process_shelf_results():
    while not _shelf_result_queue.empty():
        try:
            pk, days, explanation = _shelf_result_queue.get_nowait()
        except queue.Empty:
            break
        if pk not in _pending_shelf: continue
        info = _pending_shelf.pop(pk)
        expiry = info["added_date"] + datetime.timedelta(days=days)
        fridge_pq.push({
            "name": info["name"], "sprite_key": info["sprite_key"],
            "count": info["count"], "added_date": info["added_date"],
            "expiry_date": expiry, "shelf_days": days,
            "explanation": explanation, "barcode": info.get("barcode", ""),
        })
        print(f"[PQ] {info['name']} x{info['count']}, {days}d, expires {expiry.strftime('%Y-%m-%d')}")

# ═══════════════════════════════════
#  食谱数据库
# ═══════════════════════════════════
RECIPES = [
    {"name": "番茄炒蛋",        "ingredients": ["tomato"],                    "emoji": ""},
    {"name": "水果沙拉",        "ingredients": ["apple", "banana", "grapes"], "emoji": ""},
    {"name": "蒜蓉蔬菜",        "ingredients": ["garlic", "cabbage"],         "emoji": ""},
    {"name": "土豆泥",          "ingredients": ["potato"],                    "emoji": ""},
    {"name": "柠檬水",          "ingredients": ["lemon"],                     "emoji": ""},
    {"name": "芒果冰沙",        "ingredients": ["mango", "banana"],           "emoji": ""},
    {"name": "黄瓜沙拉",        "ingredients": ["cucumber", "onion"],         "emoji": ""},
    {"name": "烤玉米",          "ingredients": ["corn"],                      "emoji": ""},
    {"name": "茄子煲",          "ingredients": ["eggplant", "garlic"],        "emoji": ""},
    {"name": "南瓜炖菜",        "ingredients": ["potato", "carrot", "onion"], "emoji": ""},
    {"name": "草莓奶昔",        "ingredients": ["strawberry"],                "emoji": ""},
    {"name": "橙汁",            "ingredients": ["orange"],                    "emoji": ""},
    {"name": "凉拌三丝",        "ingredients": ["carrot", "cucumber", "cabbage"], "emoji": ""},
    {"name": "蒜蓉烤茄子",      "ingredients": ["eggplant", "garlic", "onion"], "emoji": ""},
    {"name": "菠萝炒饭",        "ingredients": ["pineapple", "corn"],         "emoji": ""},
    {"name": "番茄汤",          "ingredients": ["tomato", "onion", "garlic"], "emoji": ""},
    {"name": "辣椒酱",          "ingredients": ["chilli pepper", "garlic"],   "emoji": ""},
    {"name": "姜茶",            "ingredients": ["ginger", "lemon"],           "emoji": ""},
    {"name": "水果拼盘",        "ingredients": ["apple", "orange", "kiwi", "strawberry"], "emoji": ""},
]

def get_recipe_suggestions(items_list):
    item_names = set()
    for item in items_list:
        label = item.get("label", "").lower()
        item_names.add(label)
        for k in LABEL_TO_SPRITE:
            if k in label: item_names.add(k)
    suggestions = []
    for recipe in RECIPES:
        needed = set(recipe["ingredients"])
        have = needed & item_names
        if have:
            suggestions.append((recipe, len(have) / len(needed)))
    suggestions.sort(key=lambda x: -x[1])
    return suggestions[:5]

# ═══════════════════════════════════
#  冰箱库存数据
# ═══════════════════════════════════
fridge_items = []
purchase_history = []

def add_to_fridge(label, sprite_key, count, category=None):
    if category is None:
        category = CATEGORY_MAP.get(label.lower(), "other")
    expiry_days = DEFAULT_EXPIRY_DAYS.get(label.lower(), 7)
    now = datetime.datetime.now()
    for item in fridge_items:
        if item["label"].lower() == label.lower():
            item["count"] += count
            item["added_date"] = now
            item["expiry_date"] = now + datetime.timedelta(days=expiry_days)
            purchase_history.append({"label": label, "count": count, "date": now})
            return
    fridge_items.append({
        "label": label, "sprite_key": sprite_key, "count": count,
        "category": category, "added_date": now,
        "expiry_date": now + datetime.timedelta(days=expiry_days),
    })
    purchase_history.append({"label": label, "count": count, "date": now})

def remove_from_fridge(idx):
    if 0 <= idx < len(fridge_items): fridge_items.pop(idx)

def get_expiry_status(item):
    remaining = (item["expiry_date"] - datetime.datetime.now()).total_seconds() / 86400
    if remaining <= 0: return "expired", 0
    elif remaining <= 2: return "warning", int(remaining) + 1
    else: return "fresh", int(remaining)

# ═══════════════════════════════════
#  主题系统
# ═══════════════════════════════════
class Theme:
    def __init__(self):
        self.dark = False; self.transition = 0.0
    def toggle(self): self.dark = not self.dark
    def update(self, dt):
        t = 1.0 if self.dark else 0.0
        self.transition += (t - self.transition) * min(1.0, dt * 6)
    def lerp(self, light, dark):
        t = self.transition
        return tuple(int(l + (d - l) * t) for l, d in zip(light, dark))
    @property
    def bg(self):           return self.lerp((255,192,203), (30,30,40))
    @property
    def text(self):         return self.lerp((0,0,0), (230,230,230))
    @property
    def text_dim(self):     return self.lerp((100,100,100), (140,140,140))
    @property
    def panel(self):        return self.lerp((255,255,255), (45,45,58))
    @property
    def panel_border(self): return self.lerp((200,200,200), (70,70,85))
    @property
    def queue_bg(self):     return self.lerp((240,240,240), (38,38,50))

theme = Theme()

# ── Colors ──
WHITE      = (255, 255, 255)
BLACK      = (0,   0,   0  )
GREEN      = (50,  200, 50 )
RED        = (200, 50,  50 )
YELLOW     = (255, 200, 0  )
ORANGE_C   = (255, 140, 0  )
BLUE       = (50,  100, 200)
DARK_GRAY  = (100, 100, 100)
BAG_BROWN  = (139, 90,  43 )
BAG_DARK   = (100, 60,  20 )
BAG_LIGHT  = (180, 130, 70 )
URGENT_RED = (255, 60,  60 )
WARN_ORANGE= (255, 165, 0  )
SAFE_GREEN = (60,  180, 60 )

CAT_COLORS = {"fruit": (255,120,80), "veggie": (80,200,100), "other": (100,160,255)}
CAT_LABELS = {"fruit": "水果", "veggie": "蔬菜", "other": "其他"}

# ═══════════════════════════════════
#  通知系统
# ═══════════════════════════════════
class Notification:
    def __init__(self, text, color=(50,200,50), duration=2.5):
        self.text = text; self.color = color; self.life = duration; self.max_life = duration
    def update(self, dt): self.life -= dt
    def draw(self, surf, y_off):
        if self.life <= 0: return
        a = max(0.0, min(1.0, min(self.life / 0.5, 1.0)))
        w = min(500, font_medium.size(self.text)[0] + 40); h = 36
        x = W // 2 - w // 2; y = 60 + y_off
        ns = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(ns, (*self.color, int(220*a)), (0,0,w,h), border_radius=10)
        surf.blit(ns, (x, y))
        ts = font_medium.render(self.text, True, WHITE)
        ts.set_alpha(int(255*a))
        surf.blit(ts, ts.get_rect(center=(x+w//2, y+h//2)))

notifications = []
def add_notification(text, color=(50,200,50)):
    notifications.append(Notification(text, color))

# ═══════════════════════════════════
#  选项卡
# ═══════════════════════════════════
TABS = ["scan", "fridge", "recipes", "stats"]
TAB_LABELS = {"scan": "扫描", "fridge": "冰箱", "recipes": "食谱", "stats": "统计"}
current_tab = "scan"
TAB_W, TAB_H, TAB_Y = 90, 36, H - 42

# ── Bag params ──
BAG_X, BAG_Y = 820, 390
BAG_W, BAG_H = 160, 185

# ═══════════════════════════════════
#  冰箱可视化参数
# ═══════════════════════════════════
FRIDGE_X, FRIDGE_Y = 760, 42
FRIDGE_W, FRIDGE_H = 420, 540

# ═══════════════════════════════════
#  PQ 面板参数
# ═══════════════════════════════════
PQ_PANEL_X = 400
PQ_PANEL_Y = 52
PQ_PANEL_W = 380
PQ_PANEL_H = 280
PQ_SCROLL_OFFSET = 0

# ════════════════════════════════
#  物理动画
# ════════════════════════════════
class FlyingFruit:
    def __init__(self, sprite_key, sx, sy, tx, ty):
        self.sprite_key = sprite_key; self.t = 0.0; self.dur = 0.38
        self.done = False; self.angle = 0.0; self.spin = random.uniform(-10, 10)
        self.p0 = (sx, sy)
        self.p1 = ((sx+tx)/2, min(sy, ty) - random.randint(60, 130))
        self.p2 = (tx, ty); self.x = float(sx); self.y = float(sy); self.trail = []
    def bezier(self, t):
        return ((1-t)**2*self.p0[0]+2*(1-t)*t*self.p1[0]+t**2*self.p2[0],
                (1-t)**2*self.p0[1]+2*(1-t)*t*self.p1[1]+t**2*self.p2[1])
    def update(self, dt):
        if self.done: return
        self.t = min(self.t + dt/self.dur, 1.0); self.angle += self.spin
        self.x, self.y = self.bezier(self.t)
        self.trail.append((self.x, self.y))
        if len(self.trail) > 10: self.trail.pop(0)
        if self.t >= 1.0: self.done = True
    def draw(self, surf):
        for i, (tx, ty) in enumerate(self.trail):
            a = int(160*(i/max(len(self.trail),1)))
            r = max(3, int(6*(i/max(len(self.trail),1))))
            s = pygame.Surface((r*2,r*2), pygame.SRCALPHA)
            pygame.draw.circle(s, (*ORANGE_C, a), (r,r), r)
            surf.blit(s, (int(tx)-r, int(ty)-r))
        sz = int(26*(0.55+0.45*self.t))
        if self.sprite_key in sprites:
            img = pygame.transform.scale(sprites[self.sprite_key], (sz,sz))
            img = pygame.transform.rotate(img, self.angle)
            surf.blit(img, img.get_rect(center=(int(self.x), int(self.y))))

class Particle:
    def __init__(self, x, y, explode=False):
        angle = random.uniform(-math.pi,0) if not explode else random.uniform(0, math.tau)
        speed = random.uniform(2,8) if not explode else random.uniform(3,12)
        self.x=float(x); self.y=float(y)
        self.vx=math.cos(angle)*speed; self.vy=math.sin(angle)*speed
        self.life=1.0; self.color=random.choice([ORANGE_C,YELLOW,(255,200,80),(255,100,0),WHITE,GREEN])
        self.r=random.randint(3, 9 if explode else 7)
    def update(self, dt):
        self.vy += 14*dt; self.x += self.vx; self.y += self.vy
        self.life -= dt*(2.2 if self.r<6 else 1.8)
    def draw(self, surf):
        if self.life<=0: return
        a=int(255*max(0,self.life))
        s=pygame.Surface((self.r*2,self.r*2),pygame.SRCALPHA)
        pygame.draw.circle(s,(*self.color,a),(self.r,self.r),self.r)
        surf.blit(s,(int(self.x)-self.r,int(self.y)-self.r))

class BagShake:
    def __init__(self): self.ox=0.0; self.oy=0.0; self.timer=0.0
    def trigger(self): self.timer=0.35
    def update(self, dt):
        if self.timer<=0: self.ox=self.oy=0.0; return
        self.timer-=dt; d=self.timer/0.35
        self.ox=math.sin(self.timer*55)*7*d; self.oy=math.sin(self.timer*42)*3*d

def draw_bag(surf, shake, fruit_key, count):
    bx=BAG_X+shake.ox; by=BAG_Y+shake.oy
    pts=[(bx-BAG_W//2+10,by),(bx+BAG_W//2-10,by),(bx+BAG_W//2-5,by+BAG_H),(bx-BAG_W//2+5,by+BAG_H)]
    pygame.draw.polygon(surf, BAG_BROWN, pts); pygame.draw.polygon(surf, BAG_DARK, pts, 3)
    for fy,a in [(by+28,2),(by+55,1)]:
        off=15+(fy-by)//8
        pygame.draw.line(surf, BAG_LIGHT, (bx-BAG_W//2+off,fy),(bx+BAG_W//2-off,fy), a)
    rp=[(bx-BAG_W//2,by-12),(bx-BAG_W//2+10,by),(bx+BAG_W//2-10,by),(bx+BAG_W//2,by-12)]
    pygame.draw.polygon(surf, BAG_LIGHT, rp); pygame.draw.polygon(surf, BAG_DARK, rp, 2)
    pygame.draw.ellipse(surf, BAG_DARK, (bx-BAG_W//2+5,by+BAG_H-12,BAG_W-10,20), 2)
    if fruit_key and fruit_key in sprites and count>0:
        cols=4; isz=20
        for i in range(min(count,12)):
            ic=pygame.transform.scale(sprites[fruit_key],(isz,isz))
            surf.blit(ic,(int(bx-BAG_W//2+22+(i%cols)*27),int(by+BAG_H-28-(i//cols)*23)))
    if count>0:
        ct=font_large.render(f"x{count}", True, WHITE)
        surf.blit(ct,(int(bx+BAG_W//2-14),int(by+BAG_H-34)))

# ═══════════════════════════════════
#  PQ 面板绘制
# ═══════════════════════════════════
def draw_pq_panel(surf, pq, mp):
    global PQ_SCROLL_OFFSET
    panel = pygame.Rect(PQ_PANEL_X, PQ_PANEL_Y, PQ_PANEL_W, PQ_PANEL_H)
    pygame.draw.rect(surf, theme.lerp((245,248,255),(40,44,55)), panel, border_radius=12)
    pygame.draw.rect(surf, BLUE, panel, 2, border_radius=12)
    # title bar
    tr = pygame.Rect(PQ_PANEL_X, PQ_PANEL_Y, PQ_PANEL_W, 34)
    pygame.draw.rect(surf, (50,100,200), tr, border_radius=12)
    pygame.draw.rect(surf, (50,100,200), pygame.Rect(PQ_PANEL_X, PQ_PANEL_Y+16, PQ_PANEL_W, 18))
    t = font_medium.render(f"冰箱 ({FRIDGE_TEMP_C}C) - 过期优先队列", True, WHITE)
    surf.blit(t, t.get_rect(centerx=panel.centerx, centery=tr.centery))

    items = pq.all_items()
    if not items:
        e = font_medium.render("空 - 添加食物后自动排序", True, theme.text_dim)
        surf.blit(e, e.get_rect(center=panel.center)); return

    now = datetime.datetime.now()
    row_h=48; vis_rows=(PQ_PANEL_H-40)//row_h
    max_scr=max(0,len(items)-vis_rows)
    PQ_SCROLL_OFFSET=min(PQ_SCROLL_OFFSET,max_scr)
    clip=pygame.Rect(PQ_PANEL_X+4,PQ_PANEL_Y+36,PQ_PANEL_W-8,PQ_PANEL_H-40)
    surf.set_clip(clip)
    for idx, item in enumerate(items):
        if idx<PQ_SCROLL_OFFSET: continue
        vi=idx-PQ_SCROLL_OFFSET
        if vi>=vis_rows+1: break
        ry=PQ_PANEL_Y+38+vi*row_h
        rr=pygame.Rect(PQ_PANEL_X+6,ry,PQ_PANEL_W-12,row_h-4)
        dl=(item["expiry_date"]-now).days
        if dl<0:   bg=(255,200,200); sc=URGENT_RED;  st=f"过期{-dl}天!"
        elif dl<=2: bg=(255,230,200); sc=WARN_ORANGE; st=f"剩{dl}天!"
        elif dl<=5: bg=(255,245,210); sc=ORANGE_C;    st=f"剩{dl}天"
        else:       bg=(220,245,220); sc=SAFE_GREEN;  st=f"剩{dl}天"
        if theme.dark: bg=tuple(c//4 for c in bg)
        pygame.draw.rect(surf, bg, rr, border_radius=8)
        pygame.draw.rect(surf, (180,180,190), rr, 1, border_radius=8)
        surf.blit(font_medium.render(f"#{idx+1}", True, theme.text_dim), (rr.x+6, rr.y+14))
        sk=item.get("sprite_key")
        if sk and sk in sprites:
            surf.blit(pygame.transform.scale(sprites[sk],(28,28)), (rr.x+38, rr.y+8))
        dn=item["name"].replace("_"," ").title()
        if len(dn)>12: dn=dn[:11]+"..."
        surf.blit(font_medium.render(f"{dn} x{item['count']}", True, theme.text), (rr.x+72, rr.y+4))
        surf.blit(font_small.render(f"到期: {item['expiry_date'].strftime('%m/%d')}", True, theme.text_dim), (rr.x+72, rr.y+26))
        ss=font_small.render(st, True, sc)
        surf.blit(ss, (rr.right-ss.get_width()-8, rr.y+14))
        if rr.collidepoint(mp) and item.get("explanation"):
            _draw_tooltip(surf, mp[0], mp[1], item["explanation"])
    surf.set_clip(None)

def _draw_tooltip(surf, mx, my, text):
    mw=240; words=text.split(); lines=[]; line=""
    for w in words:
        test=line+" "+w if line else w
        if font_tiny.size(test)[0]>mw:
            if line: lines.append(line); line=w
        else: line=test
    if line: lines.append(line)
    if not lines: return
    lh=16; tw=max(font_tiny.size(l)[0] for l in lines)+16; th=len(lines)*lh+12
    tx=min(mx+14,W-tw-4); ty=max(my-th-6,4)
    ts=pygame.Surface((tw,th),pygame.SRCALPHA); ts.fill((40,40,40,220))
    for i,l in enumerate(lines):
        ts.blit(font_tiny.render(l,True,WHITE),(8,6+i*lh))
    surf.blit(ts,(tx,ty))

# ═══════════════════════════════════
#  冰箱可视化
# ═══════════════════════════════════
TRASH_RECT = pygame.Rect(FRIDGE_X+FRIDGE_W-70, FRIDGE_Y+FRIDGE_H-60, 60, 60)

def draw_fridge(surf, mp):
    fx,fy,fw,fh = FRIDGE_X,FRIDGE_Y,FRIDGE_W,FRIDGE_H
    pygame.draw.rect(surf, theme.lerp((220,230,240),(55,60,75)), (fx-8,fy-8,fw+16,fh+16), border_radius=14)
    pygame.draw.rect(surf, theme.lerp((200,210,220),(70,75,90)), (fx-8,fy-8,fw+16,fh+16), 3, border_radius=14)
    pygame.draw.rect(surf, theme.lerp((245,248,255),(40,44,55)), (fx,fy,fw,fh), border_radius=8)

    by_cat={"fruit":[],"veggie":[],"other":[]}
    for i,item in enumerate(fridge_items):
        c=item.get("category","other")
        if c not in by_cat: c="other"
        by_cat[c].append((i,item))

    shelf_cats=["fruit","veggie","other"]; shelf_h=fh//3
    for si,cat in enumerate(shelf_cats):
        sy=fy+si*shelf_h; items=by_cat[cat]
        cc=CAT_COLORS.get(cat,(150,150,150))
        lr=pygame.Rect(fx+4,sy+2,76,22)
        pygame.draw.rect(surf, cc, lr, border_radius=6)
        surf.blit(font_small.render(CAT_LABELS.get(cat,cat), True, WHITE), font_small.render(CAT_LABELS.get(cat,cat), True, WHITE).get_rect(center=lr.center))
        if si>0: pygame.draw.line(surf, theme.panel_border, (fx+8,sy),(fx+fw-8,sy), 2)
        cols=6; isz=44
        for ji,(gi,item) in enumerate(items):
            col=ji%cols; row=ji//cols
            ix=fx+14+col*(isz+12); iy=sy+28+row*(isz+22)
            if iy+isz>sy+shelf_h-4: break
            ir=pygame.Rect(ix,iy,isz,isz+18)
            status,dl=get_expiry_status(item)
            if status=="expired": bc=(220,30,30); bgc=(255,210,210) if not theme.dark else (80,30,30)
            elif status=="warning": bc=(255,180,0); bgc=(255,245,200) if not theme.dark else (80,70,20)
            else: bc=theme.panel_border; bgc=theme.panel
            if ir.collidepoint(mp): bgc=theme.lerp((230,240,255),(60,65,85))
            pygame.draw.rect(surf, bgc, ir, border_radius=8)
            pygame.draw.rect(surf, bc, ir, 2, border_radius=8)
            sk=item.get("sprite_key")
            if sk and sk in sprites:
                surf.blit(pygame.transform.scale(sprites[sk],(isz-8,isz-8)),(ix+4,iy+2))
            surf.blit(font_tiny.render(f"x{item['count']}", True, theme.text),(ix+2,iy+isz))
            if status=="expired": es=font_tiny.render("过期!", True, (220,30,30))
            elif status=="warning": es=font_tiny.render(f"{dl}天", True, (200,140,0))
            else: es=font_tiny.render(f"{dl}天", True, theme.text_dim)
            surf.blit(es,(ix+isz-22,iy+isz))
    # trash
    tc=(220,60,60) if TRASH_RECT.collidepoint(mp) else theme.text_dim
    pygame.draw.rect(surf, tc, TRASH_RECT, border_radius=10)
    surf.blit(font_large.render("X", True, WHITE), font_large.render("X", True, WHITE).get_rect(center=TRASH_RECT.center))

# ═══════════════════════════════════
#  食谱页面
# ═══════════════════════════════════
def draw_recipes_tab(surf, mp):
    surf.blit(font_large.render("根据冰箱食材推荐食谱", True, theme.text), (60,60))
    if not fridge_items:
        surf.blit(font_medium.render("冰箱空空的... 先去扫描添加食物吧!", True, theme.text_dim),(60,110)); return
    suggestions=get_recipe_suggestions(fridge_items)
    if not suggestions:
        surf.blit(font_medium.render("暂无匹配食谱, 试着多添加食材!", True, theme.text_dim),(60,110)); return
    for i,(recipe,ratio) in enumerate(suggestions):
        ry=110+i*100; card=pygame.Rect(50,ry,W-100,88)
        pygame.draw.rect(surf, theme.panel, card, border_radius=12)
        pygame.draw.rect(surf, theme.panel_border, card, 2, border_radius=12)
        bw=int(200*ratio); bc=GREEN if ratio>=0.8 else YELLOW if ratio>=0.5 else (200,100,100)
        pygame.draw.rect(surf, bc, (card.right-220,ry+12,bw,14), border_radius=4)
        surf.blit(font_small.render(f"{ratio:.0%} 匹配", True, theme.text_dim),(card.right-220,ry+30))
        surf.blit(font_large.render(recipe["name"], True, theme.text),(card.x+18,ry+12))
        surf.blit(font_small.render(f"食材: {', '.join(recipe['ingredients'])}", True, theme.text_dim),(card.x+18,ry+48))
        hs={it["label"].lower() for it in fridge_items}
        missing=[ing for ing in recipe["ingredients"] if ing not in hs]
        if missing: surf.blit(font_small.render(f"还缺: {', '.join(missing)}", True, RED),(card.x+18,ry+66))
        else: surf.blit(font_small.render("食材齐全! 可以做了", True, GREEN),(card.x+18,ry+66))

# ═══════════════════════════════════
#  统计页面
# ═══════════════════════════════════
def draw_stats_tab(surf, mp):
    surf.blit(font_large.render("购买统计", True, theme.text),(60,60))
    ti=sum(i["count"] for i in fridge_items); tt=len(fridge_items)
    exp=sum(1 for i in fridge_items if get_expiry_status(i)[0]=="expired")
    wrn=sum(1 for i in fridge_items if get_expiry_status(i)[0]=="warning")
    stats=[("冰箱总数",f"{ti} 件"),("种类",f"{tt} 种"),("即将过期",f"{wrn} 件"),("已过期",f"{exp} 件"),("历史购买",f"{len(purchase_history)} 次")]
    for i,(label,value) in enumerate(stats):
        card=pygame.Rect(60,110+i*64,320,52)
        pygame.draw.rect(surf, theme.panel, card, border_radius=10)
        pygame.draw.rect(surf, theme.panel_border, card, 2, border_radius=10)
        surf.blit(font_medium.render(label, True, theme.text),(card.x+14,card.y+8))
        vs=font_large.render(value, True, ORANGE_C)
        surf.blit(vs, vs.get_rect(right=card.right-14, centery=card.centery))
    # pie chart
    px,py,pr=620,280,100
    cc={"fruit":0,"veggie":0,"other":0}
    for it in fridge_items: cc[it.get("category","other")]=cc.get(it.get("category","other"),0)+it["count"]
    total=sum(cc.values())
    if total>0:
        surf.blit(font_medium.render("分类占比", True, theme.text), font_medium.render("分类占比", True, theme.text).get_rect(centerx=px, bottom=py-pr-12))
        sa=-math.pi/2
        for cat,cnt in cc.items():
            if cnt==0: continue
            sweep=2*math.pi*cnt/total; ea=sa+sweep
            pts=[(px,py)]+[(px+pr*math.cos(a),py+pr*math.sin(a)) for a in np.linspace(sa,ea,30)]+[(px,py)]
            col=CAT_COLORS.get(cat,(150,150,150))
            if len(pts)>=3: pygame.draw.polygon(surf,col,pts); pygame.draw.polygon(surf,theme.panel_border,pts,2)
            ma=(sa+ea)/2
            ls=font_small.render(f"{CAT_LABELS.get(cat,cat)} {cnt}", True, theme.text)
            surf.blit(ls,ls.get_rect(center=(int(px+(pr+24)*math.cos(ma)),int(py+(pr+24)*math.sin(ma)))))
            sa=ea
    # recent
    surf.blit(font_medium.render("最近购买:", True, theme.text),(480,430))
    for i,rec in enumerate(reversed(purchase_history[-8:])):
        surf.blit(font_small.render(f"  {rec['date'].strftime('%H:%M')}  {rec['label'].title()} x{rec['count']}", True, theme.text_dim),(480,458+i*22))

# ── Queue display ──
shopping_queue = []
def draw_queue(surf, fk, bc, ql):
    qx,qy=50,618
    qbg=pygame.Surface((W-20,40),pygame.SRCALPHA); qbg.fill((*theme.queue_bg,180)); surf.blit(qbg,(10,qy-10))
    surf.blit(font_medium.render("队列:", True, theme.text),(qx,qy))
    if ql:
        ix=qx+55
        for entry in ql:
            sk=entry[0]; cnt=entry[1]; lbl=entry[2] if len(entry)>2 else ""
            if sk and sk in sprites: surf.blit(pygame.transform.scale(sprites[sk],(36,36)),(ix,qy-4))
            surf.blit(font_medium.render(f"x{cnt}", True, ORANGE_C),(ix+38,qy+8))
            if lbl and lbl!=sk:
                short=lbl[:10]+"..." if len(lbl)>10 else lbl
                surf.blit(font_small.render(short, True, theme.text_dim),(ix,qy-18))
            ix+=100
    else:
        surf.blit(font_medium.render("-", True, theme.text_dim),(qx+55,qy))

# ── OK button ──
class OKButton:
    def __init__(self):
        self.rect=pygame.Rect(1010,560,140,65); self.hovered=False; self.clicked=False; self.pulse=0.0
    def update(self,dt,mp): self.hovered=self.rect.collidepoint(mp); self.pulse+=dt*3
    def draw(self,surf):
        sc=1.0+0.04*math.sin(self.pulse)
        w,h=int(self.rect.width*sc),int(self.rect.height*sc)
        r=pygame.Rect(self.rect.centerx-w//2,self.rect.centery-h//2,w,h)
        pygame.draw.rect(surf,(30,180,30) if self.hovered else (50,160,50),r,border_radius=12)
        pygame.draw.rect(surf,(20,120,20),r,3,border_radius=12)
        surf.blit(font_large.render("OK", True, WHITE), font_large.render("OK", True, WHITE).get_rect(center=r.center))
    def handle(self,event):
        if event.type==pygame.MOUSEBUTTONDOWN and self.rect.collidepoint(event.pos): self.clicked=True

# ════════════════════════════════
#  摄像头线程
# ════════════════════════════════
cv_queue = queue.Queue()
CAM_W, CAM_H = 320, 240
def camera_thread():
    cap=cv2.VideoCapture(0)
    if not cap.isOpened(): print("Cannot open camera"); return
    while True:
        ret,frame=cap.read()
        if ret:
            if cv_queue.qsize()>=2: cv_queue.get()
            cv_queue.put(frame)
threading.Thread(target=camera_thread, daemon=True).start()

# ════════════════════════════════
#  模型加载
# ════════════════════════════════
print("Loading model...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
hf_model = AutoModelForImageClassification.from_pretrained("jazzmacedo/fruits-and-vegetables-detector-36")
hf_model.to(device); hf_model.eval()
if device.type=="cuda": hf_model=hf_model.half(); print("FP16 enabled")
HF_LABELS = list(hf_model.config.id2label.values())
INFER_SIZE = 160
_normalize = transforms.Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])
_to_tensor = transforms.ToTensor()
print("Warmup...")
try:
    dummy=torch.zeros(1,3,INFER_SIZE,INFER_SIZE).to(device)
    if device.type=="cuda": dummy=dummy.half()
    with torch.no_grad():
        for _ in range(3): hf_model(dummy)
    print("Warmup done")
except Exception as e: print(f"Warmup skip: {e}")

def classify_frame(frame_bgr):
    small=cv2.resize(frame_bgr,(INFER_SIZE,INFER_SIZE))
    rgb=cv2.cvtColor(small,cv2.COLOR_BGR2RGB)
    tensor=_normalize(_to_tensor(rgb)).unsqueeze(0).to(device)
    if device.type=="cuda": tensor=tensor.half()
    with torch.no_grad():
        probs=torch.softmax(hf_model(tensor).logits.float(),dim=1)
        conf,idx=torch.max(probs,dim=1)
        entropy=-torch.sum(probs*torch.log(probs+1e-9),dim=1).item()
    return HF_LABELS[idx.item()], conf.item(), entropy

# ════════════════════════════════
#  推理线程 — 防误识别
# ════════════════════════════════
detect_queue = queue.Queue(maxsize=1)
CONF_THRESH          = 0.82
ENTROPY_MAX          = 2.5
STABLE_FRAMES_NEEDED = 4
SCENE_CHANGE_THRESH  = 18.0

_det_debug = {"raw_label":"","raw_conf":0.0,"entropy":0.0,"stable_count":0,"scene_diff":0.0,"reject_reason":""}

def detection_thread():
    stable_label=""; stable_count=0; prev_gray=None
    while True:
        if not cv_queue.empty():
            frame=list(cv_queue.queue)[-1]
            cur_gray=cv2.cvtColor(cv2.resize(frame,(80,60)),cv2.COLOR_BGR2GRAY)
            mean_diff=0.0; scene_changed=True
            if prev_gray is not None:
                mean_diff=float(np.mean(cv2.absdiff(cur_gray,prev_gray)))
                scene_changed=mean_diff>SCENE_CHANGE_THRESH
            prev_gray=cur_gray; _det_debug["scene_diff"]=mean_diff
            if not scene_changed:
                stable_count=0; _det_debug["reject_reason"]=f"静止(diff={mean_diff:.1f})"; _det_debug["stable_count"]=0
                time.sleep(0.08); continue
            label,conf,entropy=classify_frame(frame)
            _det_debug["raw_label"]=label; _det_debug["raw_conf"]=conf; _det_debug["entropy"]=entropy
            if conf<CONF_THRESH:
                stable_count=0; stable_label=""
                _det_debug["reject_reason"]=f"置信度低({conf:.0%}<{CONF_THRESH:.0%})"; _det_debug["stable_count"]=0
                time.sleep(0.08); continue
            if entropy>ENTROPY_MAX:
                stable_count=0; stable_label=""
                _det_debug["reject_reason"]=f"不确定(熵={entropy:.2f})"; _det_debug["stable_count"]=0
                time.sleep(0.08); continue
            if label==stable_label: stable_count+=1
            else: stable_label=label; stable_count=1
            _det_debug["stable_count"]=stable_count
            if stable_count<STABLE_FRAMES_NEEDED:
                _det_debug["reject_reason"]=f"稳定中({stable_count}/{STABLE_FRAMES_NEEDED})"
            else:
                _det_debug["reject_reason"]=""
                if detect_queue.full():
                    try: detect_queue.get_nowait()
                    except: pass
                detect_queue.put((label,conf)); stable_count=0
        time.sleep(0.08)
threading.Thread(target=detection_thread, daemon=True).start()

# ── 条码线程 ──
barcode_raw_queue=queue.Queue(maxsize=2); _bc_scan_active=threading.Event()

def _suppress_stderr_decode(gray):
    import os as _os
    old_fd=_os.dup(2)
    try:
        nul=_os.open(_os.devnull,_os.O_WRONLY); _os.dup2(nul,2); _os.close(nul)
        return pyzbar_decode(gray)
    finally: _os.dup2(old_fd,2); _os.close(old_fd)

def barcode_scan_thread():
    last_code=""
    while True:
        _bc_scan_active.wait()
        if cv_queue.empty(): time.sleep(0.05); continue
        frame=list(cv_queue.queue)[-1]
        if not PYZBAR_OK: time.sleep(0.1); continue
        results=[]
        for scale in (1.0,1.5):
            if scale==1.0: gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            else:
                h,w=frame.shape[:2]; gray=cv2.cvtColor(cv2.resize(frame,(int(w*scale),int(h*scale))),cv2.COLOR_BGR2GRAY)
            gray=cv2.equalizeHist(gray); decoded=_suppress_stderr_decode(gray)
            if decoded: results=decoded; break
        if results:
            for bc in results:
                code=bc.data.decode("utf-8",errors="replace").strip()
                if code and code!=last_code:
                    last_code=code
                    if barcode_raw_queue.full():
                        try: barcode_raw_queue.get_nowait()
                        except: pass
                    barcode_raw_queue.put((code,[(bc.rect.left,bc.rect.top,bc.rect.width,bc.rect.height)])); break
        else: last_code=""
        time.sleep(0.08)
threading.Thread(target=barcode_scan_thread, daemon=True).start()

# ════════════════════════════════
#  状态机
# ════════════════════════════════
STATE_IDLE="idle"; STATE_ASK="ask"; STATE_BAGGING="bagging"; STATE_DONE="done"; STATE_BARCODE="barcode"
state=STATE_IDLE

barcode_result_queue=queue.Queue(maxsize=1); barcode_last_scan=""; barcode_cooldown=0.0
barcode_overlay_rects=[]; barcode_lookup_busy=False

def lookup_barcode(code_str):
    try:
        url=f"https://world.openfoodfacts.org/api/v0/product/{code_str}.json"
        req=urllib.request.Request(url, headers={"User-Agent":"FridgeBud/1.0"})
        with urllib.request.urlopen(req,timeout=5) as resp: data=json.loads(resp.read())
        if data.get("status")==1:
            p=data.get("product",{}); name=(p.get("product_name_zh") or p.get("product_name_en") or p.get("product_name") or "").strip()
            return name if name else None
    except: pass
    return None

def barcode_lookup_thread(code_str):
    global barcode_lookup_busy
    name=lookup_barcode(code_str); item=(code_str, name or code_str)
    if barcode_result_queue.full():
        try: barcode_result_queue.get_nowait()
        except: pass
    barcode_result_queue.put(item); barcode_lookup_busy=False

class BarcodeDialog:
    def __init__(self, code, name):
        self.code=code; self.name=name; self.count=1; self.choice=None
        self.btn_add=pygame.Rect(630,460,160,52); self.btn_skip=pygame.Rect(810,460,140,52)
        self.btn_plus=pygame.Rect(790,395,44,44); self.btn_minus=pygame.Rect(630,395,44,44)
    def update(self, dt): pass
    def draw(self, surf, mp):
        ov=pygame.Surface((W,H),pygame.SRCALPHA); ov.fill((0,0,0,110)); surf.blit(ov,(0,0))
        box=pygame.Rect(590,290,440,265)
        pygame.draw.rect(surf,WHITE,box,border_radius=18); pygame.draw.rect(surf,(50,120,220),box,3,border_radius=18)
        surf.blit(font_large.render("条码商品",True,(50,120,220)), font_large.render("条码商品",True,(50,120,220)).get_rect(centerx=box.centerx,top=box.y+14))
        dn=self.name if len(self.name)<=24 else self.name[:22]+"..."
        surf.blit(font_large.render(dn,True,BLACK), font_large.render(dn,True,BLACK).get_rect(centerx=box.centerx,top=box.y+54))
        surf.blit(font_small.render(f"条码: {self.code}",True,DARK_GRAY), font_small.render(f"条码: {self.code}",True,DARK_GRAY).get_rect(centerx=box.centerx,top=box.y+88))
        surf.blit(font_medium.render("数量:",True,BLACK),(box.x+30,box.y+138))
        for btn,lbl in [(self.btn_minus,"-"),(self.btn_plus,"+")]:
            c=(170,170,170) if btn.collidepoint(mp) else (200,200,200)
            pygame.draw.rect(surf,c,btn,border_radius=8)
            surf.blit(font_large.render(lbl,True,BLACK),font_large.render(lbl,True,BLACK).get_rect(center=btn.center))
        surf.blit(font_xl.render(str(self.count),True,ORANGE_C), font_xl.render(str(self.count),True,ORANGE_C).get_rect(centerx=box.centerx,centery=self.btn_plus.centery))
        ca=(30,150,30) if self.btn_add.collidepoint(mp) else GREEN
        pygame.draw.rect(surf,ca,self.btn_add,border_radius=12)
        surf.blit(font_large.render("加入冰箱",True,WHITE), font_large.render("加入冰箱",True,WHITE).get_rect(center=self.btn_add.center))
        cs=(210,40,40) if self.btn_skip.collidepoint(mp) else RED
        pygame.draw.rect(surf,cs,self.btn_skip,border_radius=12)
        surf.blit(font_medium.render("跳过",True,WHITE), font_medium.render("跳过",True,WHITE).get_rect(center=self.btn_skip.center))
    def handle(self, event):
        if event.type==pygame.MOUSEBUTTONDOWN:
            if self.btn_add.collidepoint(event.pos): self.choice="add"
            if self.btn_skip.collidepoint(event.pos): self.choice="skip"
            if self.btn_plus.collidepoint(event.pos): self.count=min(99,self.count+1)
            if self.btn_minus.collidepoint(event.pos): self.count=max(1,self.count-1)

barcode_dialog=None

# ── 按钮 ──
MODE_BTN=pygame.Rect(390,14,185,38)
def draw_mode_btn(surf,mp):
    is_bc=state==STATE_BARCODE; col=(50,120,220) if is_bc else (80,80,80)
    if MODE_BTN.collidepoint(mp): col=tuple(min(255,c+30) for c in col)
    pygame.draw.rect(surf,col,MODE_BTN,border_radius=10)
    lbl="摄像头识别" if is_bc else "扫条码"
    surf.blit(font_medium.render(lbl,True,WHITE), font_medium.render(lbl,True,WHITE).get_rect(center=MODE_BTN.center))

DARK_BTN=pygame.Rect(590,14,120,38)
def draw_dark_btn(surf,mp):
    c=(60,60,70) if theme.dark else (180,180,190)
    if DARK_BTN.collidepoint(mp): c=tuple(min(255,x+20) for x in c)
    pygame.draw.rect(surf,c,DARK_BTN,border_radius=10)
    lbl="亮色" if theme.dark else "暗色"; tc=WHITE if theme.dark else BLACK
    surf.blit(font_medium.render(lbl,True,tc), font_medium.render(lbl,True,tc).get_rect(center=DARK_BTN.center))

# ── 状态变量 ──
cur_label=""; cur_sprite=None; cur_conf=0.0
last_label_disp=""; last_conf_disp=0.0
bag_count=0; bag_sprite=None
flying=[]; particles=[]; bag_shake=BagShake(); ok_button=OKButton(); done_parts=[]
detect_cooldown=0.0; click_pending=0; click_timer=0.0; CLICK_INTERVAL=0.18

class AskDialog:
    def __init__(self, label, sprite_key, conf):
        self.label=label; self.sprite_key=sprite_key; self.conf=conf
        self.btn_one=pygame.Rect(640,440,160,56); self.btn_many=pygame.Rect(820,440,160,56)
        self.btn_skip=pygame.Rect(730,510,130,40); self.choice=None; self.pulse=0.0
    def update(self,dt): self.pulse+=dt*4
    def draw(self, surf, mp):
        ov=pygame.Surface((W,H),pygame.SRCALPHA); ov.fill((0,0,0,110)); surf.blit(ov,(0,0))
        box=pygame.Rect(590,300,420,280)
        pygame.draw.rect(surf,WHITE,box,border_radius=18); pygame.draw.rect(surf,ORANGE_C,box,3,border_radius=18)
        if self.sprite_key in sprites:
            surf.blit(pygame.transform.scale(sprites[self.sprite_key],(56,56)),(box.centerx-28,box.y+18))
        surf.blit(font_large.render(self.label.replace("_"," ").title(),True,BLACK), font_large.render(self.label.replace("_"," ").title(),True,BLACK).get_rect(centerx=box.centerx,top=box.y+82))
        surf.blit(font_medium.render(f"置信度 {self.conf:.0%}",True,DARK_GRAY), font_medium.render(f"置信度 {self.conf:.0%}",True,DARK_GRAY).get_rect(centerx=box.centerx,top=box.y+114))
        surf.blit(font_large.render("加几个?",True,BLACK), font_large.render("加几个?",True,BLACK).get_rect(centerx=box.centerx,top=box.y+148))
        c1=(40,190,40) if self.btn_one.collidepoint(mp) else GREEN
        pygame.draw.rect(surf,c1,self.btn_one,border_radius=12)
        surf.blit(font_large.render("1 个",True,WHITE), font_large.render("1 个",True,WHITE).get_rect(center=self.btn_one.center))
        cm=(220,120,20) if self.btn_many.collidepoint(mp) else (255,160,30)
        pygame.draw.rect(surf,cm,self.btn_many,border_radius=12)
        surf.blit(font_large.render("多 个",True,WHITE), font_large.render("多 个",True,WHITE).get_rect(center=self.btn_many.center))
        cs=RED if self.btn_skip.collidepoint(mp) else (160,50,50)
        pygame.draw.rect(surf,cs,self.btn_skip,border_radius=8)
        surf.blit(font_medium.render("跳过",True,WHITE), font_medium.render("跳过",True,WHITE).get_rect(center=self.btn_skip.center))
    def handle(self, event):
        if event.type==pygame.MOUSEBUTTONDOWN:
            if self.btn_one.collidepoint(event.pos): self.choice=1
            if self.btn_many.collidepoint(event.pos): self.choice="many"
            if self.btn_skip.collidepoint(event.pos): self.choice="skip"
ask_dialog=None

# ═══════════════════════════════════
#  选项卡绘制
# ═══════════════════════════════════
def draw_tabs(surf,mp):
    tw=len(TABS)*(TAB_W+8); sx=W//2-tw//2
    for i,tab in enumerate(TABS):
        tx=sx+i*(TAB_W+8); rect=pygame.Rect(tx,TAB_Y,TAB_W,TAB_H)
        active=tab==current_tab; hov=rect.collidepoint(mp)
        col=ORANGE_C if active else theme.lerp((200,200,210),(80,80,100)) if hov else theme.lerp((170,170,180),(60,60,75))
        pygame.draw.rect(surf,col,rect,border_radius=8)
        tc=WHITE if active else theme.text
        surf.blit(font_small.render(TAB_LABELS[tab],True,tc), font_small.render(TAB_LABELS[tab],True,tc).get_rect(center=rect.center))

def handle_tab_click(pos):
    global current_tab
    tw=len(TABS)*(TAB_W+8); sx=W//2-tw//2
    for i,tab in enumerate(TABS):
        rect=pygame.Rect(sx+i*(TAB_W+8),TAB_Y,TAB_W,TAB_H)
        if rect.collidepoint(pos): current_tab=tab; return True
    return False

# ════════════════════════════════
#  主循环
# ════════════════════════════════
running=True; dt=0.0; cam_frame_latest=None

while running:
    dt=clock.tick(60)/1000.0; mp=pygame.mouse.get_pos()
    if not cv_queue.empty(): cam_frame_latest=cv_queue.get()
    theme.update(dt)
    for n in notifications[:]:
        n.update(dt)
        if n.life<=0: notifications.remove(n)

    if state==STATE_BARCODE: _bc_scan_active.set()
    else: _bc_scan_active.clear()

    if state==STATE_BARCODE and barcode_dialog is None and barcode_cooldown<=0:
        if not barcode_raw_queue.empty():
            raw_code,raw_rects=barcode_raw_queue.get()
            barcode_overlay_rects.clear(); barcode_overlay_rects.extend(raw_rects)
            if not barcode_lookup_busy:
                barcode_lookup_busy=True; barcode_cooldown=2.5
                threading.Thread(target=barcode_lookup_thread,args=(raw_code,),daemon=True).start()
    if barcode_cooldown>0: barcode_cooldown-=dt
    if not barcode_result_queue.empty() and barcode_dialog is None:
        code,name=barcode_result_queue.get(); barcode_dialog=BarcodeDialog(code,name); barcode_overlay_rects.clear()
    if barcode_dialog: barcode_dialog.update(dt)

    if state==STATE_IDLE and detect_cooldown<=0:
        if not detect_queue.empty():
            lbl,conf=detect_queue.get(); skey=label_to_sprite(lbl)
            last_label_disp=lbl; last_conf_disp=conf
            if skey:
                cur_label=lbl; cur_sprite=skey; cur_conf=conf
                ask_dialog=AskDialog(lbl,skey,conf); state=STATE_ASK
    if detect_cooldown>0: detect_cooldown-=dt

    process_shelf_results()

    for fo in flying[:]:
        fo.update(dt)
        if fo.done:
            flying.remove(fo)
            for _ in range(14): particles.append(Particle(BAG_X,BAG_Y+5))
            bag_shake.trigger()
    for p in particles[:]:
        p.update(dt)
        if p.life<=0: particles.remove(p)
    for p in done_parts[:]:
        p.update(dt)
        if p.life<=0: done_parts.remove(p)
    bag_shake.update(dt); ok_button.update(dt,mp)
    if ask_dialog: ask_dialog.update(dt)
    if click_pending>0:
        click_timer-=dt
        if click_timer<=0:
            flying.append(FlyingFruit(cur_sprite,380+random.randint(-20,20),180+random.randint(-25,25),BAG_X,BAG_Y+8))
            bag_count+=1; click_pending-=1; click_timer=CLICK_INTERVAL

    # ════ 绘制 ════
    screen.fill(theme.bg)
    draw_tabs(screen,mp); draw_dark_btn(screen,mp)

    if current_tab=="scan":
        screen.blit(font_medium.render("摄像头识别",True,theme.text),(50,20))
        if cam_frame_latest is not None:
            disp=cv2.cvtColor(cv2.resize(cam_frame_latest,(CAM_W,CAM_H)),cv2.COLOR_BGR2RGB)
            screen.blit(pygame.surfarray.make_surface(np.flipud(np.rot90(disp))),(50,52))
        if state==STATE_BARCODE and cam_frame_latest is not None:
            screen.blit(font_medium.render("对准条码..." if not barcode_lookup_busy else "查询中...",True,(50,120,220)),(50,308))
            for (bx2,by2,bw2,bh2) in barcode_overlay_rects:
                sx2=int(bx2*CAM_W/cam_frame_latest.shape[1])+50; sy2=int(by2*CAM_H/cam_frame_latest.shape[0])+52
                sw2=int(bw2*CAM_W/cam_frame_latest.shape[1]); sh2=int(bh2*CAM_H/cam_frame_latest.shape[0])
                pygame.draw.rect(screen,(50,220,50),(sx2,sy2,sw2,sh2),3)
        draw_mode_btn(screen,mp)
        if last_label_disp and state!=STATE_BARCODE:
            screen.blit(font_small.render(f"识别: {last_label_disp}  ({last_conf_disp:.0%})",True,theme.text),(50,308))
        # debug info
        if state!=STATE_BARCODE:
            dbg=_det_debug; rl=dbg.get("raw_label","")
            if rl:
                screen.blit(font_tiny.render(f"原始: {rl} {dbg['raw_conf']:.0%}  熵:{dbg['entropy']:.1f}  稳定:{dbg['stable_count']}/{STABLE_FRAMES_NEEDED}",True,theme.text_dim),(50,328))
            rej=dbg.get("reject_reason","")
            if rej: screen.blit(font_tiny.render(f"[过滤] {rej}",True,RED),(50,344))
            elif rl: screen.blit(font_tiny.render("识别通过",True,GREEN),(50,344))
        if state==STATE_IDLE:
            screen.blit(font_medium.render("把食物对准摄像头...",True,theme.text_dim),(50,364))
        # PQ panel
        draw_pq_panel(screen, fridge_pq, mp)
        temp_txt=font_medium.render(f"{FRIDGE_TEMP_C}C",True,BLUE)
        screen.blit(temp_txt,(PQ_PANEL_X+PQ_PANEL_W-50,PQ_PANEL_Y-22))
        if _pending_shelf:
            screen.blit(font_small.render(f"正在估算 {len(_pending_shelf)} 个商品保质期...",True,BLUE),(PQ_PANEL_X,PQ_PANEL_Y+PQ_PANEL_H+8))
        # bag
        if state in (STATE_BAGGING,STATE_DONE) or bag_count>0:
            screen.blit(font_medium.render("购物袋",True,theme.text),(BAG_X-30,BAG_Y-35))
            draw_bag(screen,bag_shake,bag_sprite,bag_count)
        for fo in flying: fo.draw(screen)
        for p in particles: p.draw(screen)
        draw_queue(screen,bag_sprite,bag_count,shopping_queue)
        if state==STATE_BAGGING:
            brect=pygame.Rect(BAG_X-BAG_W//2-12,BAG_Y-25,BAG_W+24,BAG_H+38)
            pw=int(3+2*math.sin(time.time()*8))
            pygame.draw.rect(screen,ORANGE_C,brect,pw,border_radius=8)
            screen.blit(font_large.render("点击添加",True,ORANGE_C), font_large.render("点击添加",True,ORANGE_C).get_rect(centerx=BAG_X,top=int(BAG_Y-46+5*math.sin(time.time()*5))))
        if bag_count>0 and state!=STATE_DONE:
            ok_button.draw(screen)
            screen.blit(font_small.render("完成",True,theme.text_dim),(ok_button.rect.centerx-14,ok_button.rect.bottom+4))
        if state==STATE_ASK and ask_dialog: ask_dialog.draw(screen,mp)
        if barcode_dialog: barcode_dialog.draw(screen,mp)
        if state==STATE_DONE:
            for p in done_parts: p.draw(screen)
            banner=pygame.Surface((W,64),pygame.SRCALPHA); banner.fill((30,160,30,210)); screen.blit(banner,(0,0))
            bx_off=W//2-80
            if bag_sprite and bag_sprite in sprites:
                screen.blit(pygame.transform.scale(sprites[bag_sprite],(44,44)),(bx_off,10)); bx_off+=52
            screen.blit(font_xl.render(f"x{bag_count} 已加入!",True,WHITE), font_xl.render(f"x{bag_count} 已加入!",True,WHITE).get_rect(midleft=(bx_off,32)))
            screen.blit(font_small.render("点OK继续 | ESC退出",True,(200,255,200)), font_small.render("点OK继续 | ESC退出",True,(200,255,200)).get_rect(centerx=W//2,top=H-58))
            ok_button.draw(screen)
            screen.blit(font_small.render("继续",True,theme.text_dim),(ok_button.rect.centerx-14,ok_button.rect.bottom+4))

    elif current_tab=="fridge":
        screen.blit(font_large.render("我的冰箱",True,theme.text),(60,20))
        expired_items=[i for i in fridge_items if get_expiry_status(i)[0]=="expired"]
        warning_items=[i for i in fridge_items if get_expiry_status(i)[0]=="warning"]
        ay=52
        if expired_items: screen.blit(font_medium.render(f"{len(expired_items)} 件已过期!",True,RED),(60,ay)); ay+=24
        if warning_items: screen.blit(font_medium.render(f"{len(warning_items)} 件即将过期",True,YELLOW),(60,ay)); ay+=24
        if not fridge_items:
            screen.blit(font_medium.render("冰箱空空的~ 去扫描添加食物吧",True,theme.text_dim),(60,120))
        else:
            lx,ly=50,max(ay+10,80)
            for i,item in enumerate(fridge_items):
                if ly+i*42>TAB_Y-50:
                    screen.blit(font_small.render(f"...还有 {len(fridge_items)-i} 项",True,theme.text_dim),(lx,ly+i*42)); break
                iy2=ly+i*42; rr2=pygame.Rect(lx,iy2,340,38)
                st2,dl2=get_expiry_status(item)
                bg2=theme.panel
                if st2=="expired": bg2=(80,20,20) if theme.dark else (255,210,210)
                elif st2=="warning": bg2=(80,70,15) if theme.dark else (255,245,200)
                pygame.draw.rect(screen,bg2,rr2,border_radius=8); pygame.draw.rect(screen,theme.panel_border,rr2,1,border_radius=8)
                sk2=item.get("sprite_key")
                if sk2 and sk2 in sprites: screen.blit(pygame.transform.scale(sprites[sk2],(28,28)),(lx+6,iy2+5))
                screen.blit(font_medium.render(f"{item['label'].title()} x{item['count']}",True,theme.text),(lx+40,iy2+8))
                if st2=="expired": screen.blit(font_small.render("过期!",True,RED),(lx+260,iy2+10))
                elif st2=="warning": screen.blit(font_small.render(f"剩{dl2}天",True,(200,140,0)),(lx+260,iy2+10))
                else: screen.blit(font_small.render(f"剩{dl2}天",True,theme.text_dim),(lx+260,iy2+10))
                dr=pygame.Rect(rr2.right-32,iy2+6,26,26); dh=dr.collidepoint(mp)
                pygame.draw.rect(screen,(220,60,60) if dh else theme.text_dim,dr,border_radius=6)
                screen.blit(font_small.render("X",True,WHITE), font_small.render("X",True,WHITE).get_rect(center=dr.center))
        draw_fridge(screen,mp)

    elif current_tab=="recipes": draw_recipes_tab(screen,mp)
    elif current_tab=="stats": draw_stats_tab(screen,mp)

    for i,n in enumerate(notifications): n.draw(screen,i*44)
    pygame.display.update()

    # ════ 事件 ════
    for event in pygame.event.get():
        if event.type==pygame.QUIT: running=False
        if event.type==pygame.KEYDOWN and event.key==pygame.K_ESCAPE: running=False
        # PQ scroll
        if event.type==pygame.MOUSEWHEEL:
            if pygame.Rect(PQ_PANEL_X,PQ_PANEL_Y,PQ_PANEL_W,PQ_PANEL_H).collidepoint(mp):
                PQ_SCROLL_OFFSET=max(0,PQ_SCROLL_OFFSET-event.y)
        if event.type==pygame.MOUSEBUTTONDOWN:
            if handle_tab_click(event.pos): continue
            if DARK_BTN.collidepoint(event.pos): theme.toggle(); continue
            # fridge tab delete
            if current_tab=="fridge":
                ey=sum(i for i in fridge_items if get_expiry_status(i)[0]=="expired")
                wy=sum(i for i in fridge_items if get_expiry_status(i)[0]=="warning")
                # simplified: just check delete buttons
                ay2=52
                if any(get_expiry_status(i)[0]=="expired" for i in fridge_items): ay2+=24
                if any(get_expiry_status(i)[0]=="warning" for i in fridge_items): ay2+=24
                ly2=max(ay2+10,80)
                for i,item in enumerate(fridge_items):
                    iy3=ly2+i*42; rr3=pygame.Rect(50,iy3,340,38)
                    dr2=pygame.Rect(rr3.right-32,iy3+6,26,26)
                    if dr2.collidepoint(event.pos):
                        rm=fridge_items[i]; remove_from_fridge(i)
                        fridge_pq.remove_by_name(rm["label"])
                        add_notification(f"已移除 {rm['label'].title()}",RED); break
            if current_tab=="scan":
                if MODE_BTN.collidepoint(event.pos):
                    if state==STATE_BARCODE:
                        state=STATE_IDLE; barcode_overlay_rects.clear(); barcode_dialog=None; barcode_cooldown=0.0
                        _bc_scan_active.clear()
                        while not barcode_raw_queue.empty():
                            try: barcode_raw_queue.get_nowait()
                            except: pass
                    elif state==STATE_IDLE: state=STATE_BARCODE; barcode_cooldown=0.0; _bc_scan_active.set()
        # barcode dialog
        if barcode_dialog:
            barcode_dialog.handle(event)
            if barcode_dialog.choice=="add":
                bn=barcode_dialog.name.lower(); bs=None
                for kw in bn.split():
                    bs=find_sprite_key(kw)
                    if bs: break
                if not bs: bs=find_sprite_key("box") or find_sprite_key("bag") or (list(sprites.keys())[0] if sprites else None)
                bc2=barcode_dialog.count; bcd=barcode_dialog.code; bnm=barcode_dialog.name
                add_to_fridge(bnm, bs, bc2, "other")
                add_to_fridge_pq(bnm, bs, bc2, barcode=bcd)
                merged=False
                for i,e in enumerate(shopping_queue):
                    if (len(e)>2 and e[2]==bnm): shopping_queue[i]=(e[0],e[1]+bc2,e[2]); merged=True; break
                if not merged: shopping_queue.append((bs,bc2,bnm))
                add_notification(f"{bnm} x{bc2} 已加入冰箱")
                barcode_dialog=None; barcode_cooldown=1.0
            elif barcode_dialog.choice=="skip": barcode_dialog=None; barcode_cooldown=1.0
        # ask dialog
        if state==STATE_ASK and ask_dialog:
            ask_dialog.handle(event)
            if ask_dialog.choice==1:
                bag_sprite=cur_sprite; flying.append(FlyingFruit(cur_sprite,380,180,BAG_X,BAG_Y+8))
                bag_count+=1; state=STATE_BAGGING; ask_dialog=None; detect_cooldown=1.2
            elif ask_dialog.choice=="many":
                bag_sprite=cur_sprite; state=STATE_BAGGING; ask_dialog=None; detect_cooldown=1.2
            elif ask_dialog.choice=="skip":
                state=STATE_IDLE; ask_dialog=None; detect_cooldown=1.5
        # bagging click
        if state==STATE_BAGGING and event.type==pygame.MOUSEBUTTONDOWN and current_tab=="scan":
            br2=pygame.Rect(BAG_X-BAG_W//2-15,BAG_Y-30,BAG_W+30,BAG_H+45)
            if br2.collidepoint(event.pos):
                if not flying:
                    flying.append(FlyingFruit(cur_sprite,380+random.randint(-20,20),180+random.randint(-25,25),BAG_X,BAG_Y+8))
                    bag_count+=1
                else: click_pending+=1; click_timer=max(click_timer,CLICK_INTERVAL)
        # OK
        ok_button.handle(event)
        if ok_button.clicked:
            ok_button.clicked=False
            if state==STATE_DONE:
                merged=False
                for i,e in enumerate(shopping_queue):
                    if e[0]==bag_sprite and (len(e)<3 or e[2]==""): shopping_queue[i]=(e[0],e[1]+bag_count,""); merged=True; break
                if not merged: shopping_queue.append((bag_sprite,bag_count,""))
                add_to_fridge(cur_label,bag_sprite,bag_count)
                add_to_fridge_pq(cur_label,bag_sprite,bag_count)
                add_notification(f"{cur_label.title()} x{bag_count} 已存入冰箱!")
                bag_count=0; bag_sprite=None; flying.clear(); particles.clear(); done_parts.clear()
                click_pending=0; detect_cooldown=1.0; state=STATE_IDLE
            elif bag_count>0:
                state=STATE_DONE; click_pending=0
                for _ in range(65): done_parts.append(Particle(W//2,H//2,explode=True))

pygame.quit(); exit()