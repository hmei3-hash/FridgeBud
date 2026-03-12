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
    print("⚠  pyzbar 未安装，条码扫描不可用。运行: pip install pyzbar")

pygame.init()
W, H = 1200, 700
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("FridgeBud ✨")
clock = pygame.time.Clock()
font_large  = pygame.font.Font(None, 32)
font_medium = pygame.font.Font(None, 24)
font_small  = pygame.font.Font(None, 20)
font_tiny   = pygame.font.Font(None, 16)
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

# ═══════════════════════════════════
#  NEW: 食物分类 & 保质期默认天数
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
#  NEW: 简易食谱数据库
# ═══════════════════════════════════
RECIPES = [
    {"name": "番茄炒蛋",        "ingredients": ["tomato"],                    "emoji": "🍳"},
    {"name": "水果沙拉",        "ingredients": ["apple", "banana", "grapes"], "emoji": "🥗"},
    {"name": "蒜蓉蔬菜",        "ingredients": ["garlic", "cabbage"],         "emoji": "🧄"},
    {"name": "土豆泥",          "ingredients": ["potato"],                    "emoji": "🥔"},
    {"name": "柠檬水",          "ingredients": ["lemon"],                     "emoji": "🍋"},
    {"name": "芒果冰沙",        "ingredients": ["mango", "banana"],           "emoji": "🥭"},
    {"name": "黄瓜沙拉",        "ingredients": ["cucumber", "onion"],         "emoji": "🥒"},
    {"name": "烤玉米",          "ingredients": ["corn"],                      "emoji": "🌽"},
    {"name": "茄子煲",          "ingredients": ["eggplant", "garlic"],        "emoji": "🍆"},
    {"name": "南瓜炖菜",        "ingredients": ["potato", "carrot", "onion"], "emoji": "🍲"},
    {"name": "草莓奶昔",        "ingredients": ["strawberry"],                "emoji": "🍓"},
    {"name": "橙汁",            "ingredients": ["orange"],                    "emoji": "🍊"},
    {"name": "凉拌三丝",        "ingredients": ["carrot", "cucumber", "cabbage"], "emoji": "🥢"},
    {"name": "蒜蓉烤茄子",      "ingredients": ["eggplant", "garlic", "onion"], "emoji": "🔥"},
    {"name": "菠萝炒饭",        "ingredients": ["pineapple", "corn"],         "emoji": "🍍"},
    {"name": "番茄汤",          "ingredients": ["tomato", "onion", "garlic"], "emoji": "🍅"},
    {"name": "辣椒酱",          "ingredients": ["chilli pepper", "garlic"],   "emoji": "🌶️"},
    {"name": "姜茶",            "ingredients": ["ginger", "lemon"],           "emoji": "🫖"},
    {"name": "水果拼盘",        "ingredients": ["apple", "orange", "kiwi", "strawberry"], "emoji": "🍉"},
]

def get_recipe_suggestions(fridge_items):
    """根据冰箱里的食材推荐食谱，返回 [(recipe, match_ratio), ...]"""
    item_names = set()
    for item in fridge_items:
        label = item.get("label", "").lower()
        item_names.add(label)
        # 也加入别名
        for k in LABEL_TO_SPRITE:
            if k in label:
                item_names.add(k)

    suggestions = []
    for recipe in RECIPES:
        needed = set(recipe["ingredients"])
        have   = needed & item_names
        if have:
            ratio = len(have) / len(needed)
            suggestions.append((recipe, ratio))

    suggestions.sort(key=lambda x: -x[1])
    return suggestions[:5]

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

# ═══════════════════════════════════
#  NEW: 主题系统（亮色 / 暗色）
# ═══════════════════════════════════
class Theme:
    def __init__(self):
        self.dark = False
        self.transition = 0.0  # 0=light, 1=dark

    def toggle(self):
        self.dark = not self.dark

    def update(self, dt):
        target = 1.0 if self.dark else 0.0
        self.transition += (target - self.transition) * min(1.0, dt * 6)

    def lerp_color(self, light, dark):
        t = self.transition
        return tuple(int(l + (d - l) * t) for l, d in zip(light, dark))

    @property
    def bg(self):          return self.lerp_color((255, 192, 203), (30, 30, 40))
    @property
    def text(self):        return self.lerp_color((0, 0, 0), (230, 230, 230))
    @property
    def text_dim(self):    return self.lerp_color((100, 100, 100), (140, 140, 140))
    @property
    def panel(self):       return self.lerp_color((255, 255, 255), (45, 45, 58))
    @property
    def panel_border(self): return self.lerp_color((200, 200, 200), (70, 70, 85))
    @property
    def accent(self):      return (255, 140, 0)
    @property
    def green(self):       return (50, 200, 50)
    @property
    def red(self):         return (200, 50, 50)
    @property
    def queue_bg(self):    return self.lerp_color((240, 240, 240), (38, 38, 50))

theme = Theme()

# ── Colors (kept for backward compat) ──
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

# ═══════════════════════════════════
#  NEW: 冰箱可视化参数
# ═══════════════════════════════════
FRIDGE_X, FRIDGE_Y = 760, 42
FRIDGE_W, FRIDGE_H = 420, 540
FRIDGE_SHELF_H     = FRIDGE_H // 4   # 4 层

# 分类颜色
CAT_COLORS = {
    "fruit":  (255, 120, 80),
    "veggie": (80, 200, 100),
    "other":  (100, 160, 255),
}
CAT_LABELS = {
    "fruit":  "🍎 水果",
    "veggie": "🥦 蔬菜",
    "other":  "📦 其他",
}

# ═══════════════════════════════════
#  NEW: 冰箱库存数据结构
# ═══════════════════════════════════
# fridge_items: list of dict {label, sprite_key, count, category, added_date, expiry_date}
fridge_items = []

# 购买历史 (for stats)
purchase_history = []   # list of {label, count, date}

def add_to_fridge(label, sprite_key, count, category=None):
    """添加食物到冰箱"""
    if category is None:
        category = CATEGORY_MAP.get(label.lower(), "other")
    expiry_days = DEFAULT_EXPIRY_DAYS.get(label.lower(), 7)
    now = datetime.datetime.now()

    # 合并同类
    for item in fridge_items:
        if item["label"].lower() == label.lower():
            item["count"] += count
            # 刷新保质期到最新
            item["added_date"] = now
            item["expiry_date"] = now + datetime.timedelta(days=expiry_days)
            purchase_history.append({"label": label, "count": count, "date": now})
            return

    fridge_items.append({
        "label":       label,
        "sprite_key":  sprite_key,
        "count":       count,
        "category":    category,
        "added_date":  now,
        "expiry_date": now + datetime.timedelta(days=expiry_days),
    })
    purchase_history.append({"label": label, "count": count, "date": now})

def remove_from_fridge(idx):
    """从冰箱移除一项"""
    if 0 <= idx < len(fridge_items):
        fridge_items.pop(idx)

def get_expiry_status(item):
    """返回 ('fresh','warning','expired') 和剩余天数"""
    now = datetime.datetime.now()
    remaining = (item["expiry_date"] - now).total_seconds() / 86400
    if remaining <= 0:
        return "expired", 0
    elif remaining <= 2:
        return "warning", int(remaining) + 1
    else:
        return "fresh", int(remaining)

# ═══════════════════════════════════
#  NEW: 选项卡系统
# ═══════════════════════════════════
# tabs: "scan" = 扫描模式, "fridge" = 冰箱查看, "recipes" = 食谱, "stats" = 统计
TABS = ["scan", "fridge", "recipes", "stats"]
TAB_LABELS = {"scan": "📷 扫描", "fridge": "🧊 冰箱", "recipes": "📖 食谱", "stats": "📊 统计"}
current_tab = "scan"
TAB_W = 90
TAB_H = 36
TAB_Y = H - 42

# ═══════════════════════════════════
#  NEW: 通知系统
# ═══════════════════════════════════
class Notification:
    def __init__(self, text, color=(50, 200, 50), duration=2.5):
        self.text = text
        self.color = color
        self.life = duration
        self.max_life = duration

    def update(self, dt):
        self.life -= dt

    def draw(self, surf, y_offset):
        if self.life <= 0: return
        alpha = min(1.0, self.life / 0.5) * min(1.0, (self.max_life - (self.max_life - self.life)) / 0.3 + 0.7)
        alpha = max(0.0, min(1.0, alpha))

        w = min(500, font_medium.size(self.text)[0] + 40)
        h = 36
        x = W // 2 - w // 2
        y = 60 + y_offset

        ns = pygame.Surface((w, h), pygame.SRCALPHA)
        a = int(220 * alpha)
        pygame.draw.rect(ns, (*self.color, a), (0, 0, w, h), border_radius=10)
        surf.blit(ns, (x, y))

        ts = font_medium.render(self.text, True, WHITE)
        ts.set_alpha(int(255 * alpha))
        surf.blit(ts, ts.get_rect(center=(x + w // 2, y + h // 2)))

notifications = []

def add_notification(text, color=(50, 200, 50)):
    notifications.append(Notification(text, color))

# ═══════════════════════════════════
#  NEW: 拖拽删除
# ═══════════════════════════════════
drag_item_idx = -1
drag_offset = (0, 0)
drag_pos = (0, 0)
TRASH_RECT = pygame.Rect(W - 80, FRIDGE_Y + FRIDGE_H - 60, 60, 60)

# ── Bag params (still used during scan mode) ──
BAG_X, BAG_Y = 820, 390
BAG_W, BAG_H = 160, 185

# ════════════════════════════════
#  物理动画类 (unchanged)
# ════════════════════════════════

class FlyingFruit:
    def __init__(self, sprite_key, start_x, start_y, target_x, target_y):
        self.sprite_key = sprite_key
        self.x = float(start_x); self.y = float(start_y)
        self.t = 0.0; self.dur = 0.38
        self.done = False
        self.angle = 0.0
        self.spin  = random.uniform(-10, 10)
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
    pts = [(bx-BAG_W//2+10,by),(bx+BAG_W//2-10,by),
           (bx+BAG_W//2-5, by+BAG_H),(bx-BAG_W//2+5, by+BAG_H)]
    pygame.draw.polygon(surf, BAG_BROWN, pts)
    pygame.draw.polygon(surf, BAG_DARK, pts, 3)
    for fy, a in [(by+28,2),(by+55,1)]:
        off = 15 + (fy-by)//8
        pygame.draw.line(surf, BAG_LIGHT, (bx-BAG_W//2+off,fy),(bx+BAG_W//2-off,fy), a)
    rp = [(bx-BAG_W//2,by-12),(bx-BAG_W//2+10,by),(bx+BAG_W//2-10,by),(bx+BAG_W//2,by-12)]
    pygame.draw.polygon(surf, BAG_LIGHT, rp)
    pygame.draw.polygon(surf, BAG_DARK, rp, 2)
    pygame.draw.ellipse(surf, BAG_DARK, (bx-BAG_W//2+5, by+BAG_H-12, BAG_W-10, 20), 2)
    if fruit_key and fruit_key in sprites and count > 0:
        cols = 4; icon_sz = 20
        for i in range(min(count, 12)):
            ic = pygame.transform.scale(sprites[fruit_key], (icon_sz, icon_sz))
            ix = bx - BAG_W//2 + 22 + (i % cols) * 27
            iy = by + BAG_H - 28 - (i // cols) * 23
            surf.blit(ic, (int(ix), int(iy)))
    if count > 0:
        ct = font_large.render(f"×{count}", True, WHITE)
        surf.blit(ct, (int(bx + BAG_W//2 - 14), int(by + BAG_H - 34)))

# ═══════════════════════════════════
#  NEW: 冰箱绘制
# ═══════════════════════════════════

def draw_fridge(surf, mp):
    """绘制冰箱可视化视图"""
    fx, fy = FRIDGE_X, FRIDGE_Y
    fw, fh = FRIDGE_W, FRIDGE_H

    # 冰箱外壳
    pygame.draw.rect(surf, theme.lerp_color((220, 230, 240), (55, 60, 75)),
                     (fx - 8, fy - 8, fw + 16, fh + 16), border_radius=14)
    pygame.draw.rect(surf, theme.lerp_color((200, 210, 220), (70, 75, 90)),
                     (fx - 8, fy - 8, fw + 16, fh + 16), 3, border_radius=14)

    # 冰箱内部
    pygame.draw.rect(surf, theme.lerp_color((245, 248, 255), (40, 44, 55)),
                     (fx, fy, fw, fh), border_radius=8)

    # 分类过滤：按类别分组
    by_cat = {"fruit": [], "veggie": [], "other": []}
    for i, item in enumerate(fridge_items):
        cat = item.get("category", "other")
        if cat not in by_cat:
            cat = "other"
        by_cat[cat].append((i, item))

    # 绘制三层（fruit, veggie, other）
    shelf_cats = ["fruit", "veggie", "other"]
    shelf_h = fh // 3

    hovered_item_idx = -1

    for si, cat in enumerate(shelf_cats):
        sy = fy + si * shelf_h
        items = by_cat[cat]

        # 层标签
        cat_label = CAT_LABELS.get(cat, cat)
        cat_col = CAT_COLORS.get(cat, (150, 150, 150))

        # 标签背景
        lbl_rect = pygame.Rect(fx + 4, sy + 2, 76, 22)
        pygame.draw.rect(surf, (*cat_col, 180) if len(cat_col) == 3 else cat_col,
                         lbl_rect, border_radius=6)
        ls = font_small.render(cat_label, True, WHITE)
        surf.blit(ls, ls.get_rect(center=lbl_rect.center))

        # 分隔线
        if si > 0:
            pygame.draw.line(surf, theme.panel_border,
                             (fx + 8, sy), (fx + fw - 8, sy), 2)

        # 食物图标网格
        cols = 6
        icon_sz = 44
        pad_x = 14
        pad_y = 28
        for ji, (global_idx, item) in enumerate(items):
            col = ji % cols
            row = ji // cols
            ix = fx + pad_x + col * (icon_sz + 12)
            iy = sy + pad_y + row * (icon_sz + 22)

            if iy + icon_sz > sy + shelf_h - 4:
                break  # 超出层高

            item_rect = pygame.Rect(ix, iy, icon_sz, icon_sz + 18)

            # 保质期颜色
            status, days_left = get_expiry_status(item)
            if status == "expired":
                border_col = (220, 30, 30)
                bg_col = (255, 200, 200) if not theme.dark else (80, 30, 30)
            elif status == "warning":
                border_col = (255, 180, 0)
                bg_col = (255, 245, 200) if not theme.dark else (80, 70, 20)
            else:
                border_col = theme.panel_border
                bg_col = theme.panel

            # 悬停检测
            is_hovered = item_rect.collidepoint(mp) and drag_item_idx < 0
            if is_hovered:
                hovered_item_idx = global_idx
                bg_col = theme.lerp_color((230, 240, 255), (60, 65, 85))

            # 背景卡片
            pygame.draw.rect(surf, bg_col, item_rect, border_radius=8)
            pygame.draw.rect(surf, border_col, item_rect, 2, border_radius=8)

            # 图标
            sk = item.get("sprite_key")
            if sk and sk in sprites:
                icon = pygame.transform.scale(sprites[sk], (icon_sz - 8, icon_sz - 8))
                surf.blit(icon, (ix + 4, iy + 2))

            # 数量
            cnt_s = font_tiny.render(f"×{item['count']}", True, theme.text)
            surf.blit(cnt_s, (ix + 2, iy + icon_sz))

            # 保质期小标
            if status == "expired":
                exp_s = font_tiny.render("过期!", True, (220, 30, 30))
            elif status == "warning":
                exp_s = font_tiny.render(f"{days_left}天", True, (200, 140, 0))
            else:
                exp_s = font_tiny.render(f"{days_left}天", True, theme.text_dim)
            surf.blit(exp_s, (ix + icon_sz - 22, iy + icon_sz))

    # 悬停提示卡片
    if hovered_item_idx >= 0 and hovered_item_idx < len(fridge_items):
        item = fridge_items[hovered_item_idx]
        status, days_left = get_expiry_status(item)
        tip_lines = [
            f"{item['label'].title()}  ×{item['count']}",
            f"保质期: {'已过期!' if status == 'expired' else f'剩余 {days_left} 天'}",
            f"添加于: {item['added_date'].strftime('%m/%d %H:%M')}",
        ]
        tip_w = max(font_small.size(l)[0] for l in tip_lines) + 20
        tip_h = len(tip_lines) * 20 + 12
        tx = min(mp[0] + 12, W - tip_w - 10)
        ty = max(mp[1] - tip_h - 8, 4)
        ts = pygame.Surface((tip_w, tip_h), pygame.SRCALPHA)
        ts.fill((*theme.panel, 240))
        surf.blit(ts, (tx, ty))
        pygame.draw.rect(surf, theme.panel_border, (tx, ty, tip_w, tip_h), 2, border_radius=6)
        for li, line in enumerate(tip_lines):
            col = (220, 30, 30) if "过期" in line else theme.text
            surf.blit(font_small.render(line, True, col), (tx + 10, ty + 6 + li * 20))

    # 垃圾桶（拖拽删除目标）
    trash_col = (220, 60, 60) if drag_item_idx >= 0 and TRASH_RECT.collidepoint(mp) else theme.text_dim
    pygame.draw.rect(surf, trash_col, TRASH_RECT, border_radius=10)
    trash_label = font_large.render("🗑️", True, WHITE)
    surf.blit(trash_label, trash_label.get_rect(center=TRASH_RECT.center))
    if drag_item_idx >= 0:
        hint = font_tiny.render("拖到这里删除", True, trash_col)
        surf.blit(hint, hint.get_rect(centerx=TRASH_RECT.centerx, top=TRASH_RECT.bottom + 4))

    return hovered_item_idx

# ═══════════════════════════════════
#  NEW: 食谱页面绘制
# ═══════════════════════════════════

def draw_recipes_tab(surf, mp):
    suggestions = get_recipe_suggestions(fridge_items)

    # 标题
    title = font_large.render("📖 根据冰箱食材推荐的食谱", True, theme.text)
    surf.blit(title, (60, 60))

    if not fridge_items:
        hint = font_medium.render("冰箱空空的... 先去扫描添加食物吧！", True, theme.text_dim)
        surf.blit(hint, (60, 110))
        return

    if not suggestions:
        hint = font_medium.render("暂无匹配的食谱，试着多添加一些食材！", True, theme.text_dim)
        surf.blit(hint, (60, 110))
        return

    for i, (recipe, ratio) in enumerate(suggestions):
        ry = 110 + i * 100
        card = pygame.Rect(50, ry, W - 100, 88)
        pygame.draw.rect(surf, theme.panel, card, border_radius=12)
        pygame.draw.rect(surf, theme.panel_border, card, 2, border_radius=12)

        # 匹配度条
        bar_w = int(200 * ratio)
        bar_col = GREEN if ratio >= 0.8 else YELLOW if ratio >= 0.5 else (200, 100, 100)
        pygame.draw.rect(surf, bar_col, (card.right - 220, ry + 12, bar_w, 14), border_radius=4)
        pct = font_small.render(f"{ratio:.0%} 匹配", True, theme.text_dim)
        surf.blit(pct, (card.right - 220, ry + 30))

        # emoji + 名字
        name_s = font_large.render(f"{recipe['emoji']}  {recipe['name']}", True, theme.text)
        surf.blit(name_s, (card.x + 18, ry + 12))

        # 所需食材
        needed = ", ".join(recipe["ingredients"])
        need_s = font_small.render(f"食材: {needed}", True, theme.text_dim)
        surf.blit(need_s, (card.x + 18, ry + 48))

        # 缺少的食材
        have_set = {item["label"].lower() for item in fridge_items}
        missing = [ing for ing in recipe["ingredients"] if ing not in have_set]
        if missing:
            miss_s = font_small.render(f"还缺: {', '.join(missing)}", True, RED)
            surf.blit(miss_s, (card.x + 18, ry + 66))
        else:
            ok_s = font_small.render("✓ 食材齐全！可以做了", True, GREEN)
            surf.blit(ok_s, (card.x + 18, ry + 66))

# ═══════════════════════════════════
#  NEW: 统计页面绘制
# ═══════════════════════════════════

def draw_stats_tab(surf, mp):
    title = font_large.render("📊 购买统计", True, theme.text)
    surf.blit(title, (60, 60))

    # 总计
    total_items = sum(item["count"] for item in fridge_items)
    total_types = len(fridge_items)
    expired = sum(1 for item in fridge_items if get_expiry_status(item)[0] == "expired")
    warning = sum(1 for item in fridge_items if get_expiry_status(item)[0] == "warning")

    stats = [
        ("🧊 冰箱总数", f"{total_items} 件"),
        ("📦 种类", f"{total_types} 种"),
        ("⚠️ 即将过期", f"{warning} 件"),
        ("❌ 已过期", f"{expired} 件"),
        ("📝 历史购买", f"{len(purchase_history)} 次"),
    ]

    for i, (label, value) in enumerate(stats):
        card = pygame.Rect(60, 110 + i * 64, 320, 52)
        pygame.draw.rect(surf, theme.panel, card, border_radius=10)
        pygame.draw.rect(surf, theme.panel_border, card, 2, border_radius=10)
        surf.blit(font_medium.render(label, True, theme.text), (card.x + 14, card.y + 8))
        vs = font_large.render(value, True, ORANGE_C)
        surf.blit(vs, vs.get_rect(right=card.right - 14, centery=card.centery))

    # 分类饼图（简易弧线）
    pie_cx, pie_cy = 620, 280
    pie_r = 100
    cat_counts = {"fruit": 0, "veggie": 0, "other": 0}
    for item in fridge_items:
        c = item.get("category", "other")
        cat_counts[c] = cat_counts.get(c, 0) + item["count"]
    total = sum(cat_counts.values())

    if total > 0:
        pie_title = font_medium.render("分类占比", True, theme.text)
        surf.blit(pie_title, pie_title.get_rect(centerx=pie_cx, bottom=pie_cy - pie_r - 12))

        start_angle = -math.pi / 2
        for cat, cnt in cat_counts.items():
            if cnt == 0: continue
            sweep = 2 * math.pi * cnt / total
            end_angle = start_angle + sweep

            # 画扇形
            points = [(pie_cx, pie_cy)]
            for a in np.linspace(start_angle, end_angle, 30):
                points.append((pie_cx + pie_r * math.cos(a), pie_cy + pie_r * math.sin(a)))
            points.append((pie_cx, pie_cy))
            col = CAT_COLORS.get(cat, (150, 150, 150))
            if len(points) >= 3:
                pygame.draw.polygon(surf, col, points)
                pygame.draw.polygon(surf, theme.panel_border, points, 2)

            # 标签
            mid_angle = (start_angle + end_angle) / 2
            lx = pie_cx + (pie_r + 24) * math.cos(mid_angle)
            ly = pie_cy + (pie_r + 24) * math.sin(mid_angle)
            ls = font_small.render(f"{CAT_LABELS[cat]} {cnt}", True, theme.text)
            surf.blit(ls, ls.get_rect(center=(int(lx), int(ly))))

            start_angle = end_angle

    # 最近购买历史
    hist_x = 480
    hist_y = 430
    surf.blit(font_medium.render("最近购买:", True, theme.text), (hist_x, hist_y))
    for i, rec in enumerate(reversed(purchase_history[-8:])):
        ry = hist_y + 28 + i * 22
        txt = f"  {rec['date'].strftime('%H:%M')}  {rec['label'].title()} ×{rec['count']}"
        surf.blit(font_small.render(txt, True, theme.text_dim), (hist_x, ry))


# ── Queue display ──
shopping_queue = []

def draw_queue(surf, fruit_key, bag_cnt, queue_list):
    qx, qy = 50, 618
    # 背景条
    qbg = pygame.Surface((W - 20, 40), pygame.SRCALPHA)
    qbg.fill((*theme.queue_bg, 180))
    surf.blit(qbg, (10, qy - 10))

    surf.blit(font_medium.render("队列:", True, theme.text), (qx, qy))
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
            if lbl and lbl != sk:
                short = lbl[:10] + "…" if len(lbl) > 10 else lbl
                ls = font_small.render(short, True, theme.text_dim)
                surf.blit(ls, (ix, qy - 18))
            ix += 100
    else:
        surf.blit(font_medium.render("—", True, theme.text_dim), (qx + 55, qy))

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
#  模型加载
# ════════════════════════════════
print("加载模型...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

hf_model = AutoModelForImageClassification.from_pretrained(
    "jazzmacedo/fruits-and-vegetables-detector-36"
)
hf_model.to(device)
hf_model.eval()

if device.type == "cuda":
    hf_model = hf_model.half()
    print("✓ FP16 推理已启用 (CUDA)")

HF_LABELS = list(hf_model.config.id2label.values())

INFER_SIZE = 160
_normalize = transforms.Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])
_to_tensor  = transforms.ToTensor()

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
    small = cv2.resize(frame_bgr, (INFER_SIZE, INFER_SIZE))
    rgb   = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    tensor = _normalize(_to_tensor(rgb)).unsqueeze(0).to(device)
    if device.type == "cuda": tensor = tensor.half()
    with torch.no_grad():
        probs = torch.softmax(hf_model(tensor).logits.float(), dim=1)
        conf, idx = torch.max(probs, dim=1)
    return HF_LABELS[idx.item()], conf.item()

# ════════════════════════════════
#  推理线程
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
        time.sleep(0.08)

threading.Thread(target=detection_thread, daemon=True).start()

# ── 条码检测线程 ──
barcode_raw_queue = queue.Queue(maxsize=2)
_bc_scan_active   = threading.Event()

def _suppress_stderr_decode(gray):
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
        _bc_scan_active.wait()
        if cv_queue.empty():
            time.sleep(0.05)
            continue
        frame = list(cv_queue.queue)[-1]
        if not PYZBAR_OK:
            time.sleep(0.1); continue
        results = []
        for scale in (1.0, 1.5):
            if scale == 1.0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                h, w = frame.shape[:2]
                big  = cv2.resize(frame, (int(w*scale), int(h*scale)))
                gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
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
            last_code = ""
        time.sleep(0.08)

threading.Thread(target=barcode_scan_thread, daemon=True).start()

# ════════════════════════════════
#  状态机
# ════════════════════════════════
STATE_IDLE    = "idle"
STATE_ASK     = "ask"
STATE_BAGGING = "bagging"
STATE_DONE    = "done"
STATE_BARCODE = "barcode"

state = STATE_IDLE

barcode_result_queue  = queue.Queue(maxsize=1)
barcode_last_scan     = ""
barcode_cooldown      = 0.0
barcode_overlay_rects = []
barcode_lookup_busy   = False

def lookup_barcode(code_str):
    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{code_str}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "FridgeBud/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
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
        title = font_large.render("条码商品", True, (50, 120, 220))
        surf.blit(title, title.get_rect(centerx=box.centerx, top=box.y + 14))
        disp_name = self.name if len(self.name) <= 24 else self.name[:22] + "…"
        ns = font_large.render(disp_name, True, BLACK)
        surf.blit(ns, ns.get_rect(centerx=box.centerx, top=box.y + 54))
        cs = font_small.render(f"条码: {self.code}", True, DARK_GRAY)
        surf.blit(cs, cs.get_rect(centerx=box.centerx, top=box.y + 88))
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

# ── 模式切换按钮 ──
MODE_BTN = pygame.Rect(390, 14, 185, 38)
def draw_mode_btn(surf, mp):
    is_bc = state == STATE_BARCODE
    col   = (50, 120, 220) if is_bc else (80, 80, 80)
    hov   = MODE_BTN.collidepoint(mp)
    if hov: col = tuple(min(255, c+30) for c in col)
    pygame.draw.rect(surf, col, MODE_BTN, border_radius=10)
    label = "📸 摄像头识别" if is_bc else "🔲 扫条码"
    ls = font_medium.render(label, True, WHITE)
    surf.blit(ls, ls.get_rect(center=MODE_BTN.center))

# ── NEW: 暗色模式按钮 ──
DARK_BTN = pygame.Rect(590, 14, 120, 38)
def draw_dark_btn(surf, mp):
    hov = DARK_BTN.collidepoint(mp)
    col = (60, 60, 70) if theme.dark else (180, 180, 190)
    if hov: col = tuple(min(255, c + 20) for c in col)
    pygame.draw.rect(surf, col, DARK_BTN, border_radius=10)
    label = "☀️ 亮色" if theme.dark else "🌙 暗色"
    text_col = WHITE if theme.dark else BLACK
    ls = font_medium.render(label, True, text_col)
    surf.blit(ls, ls.get_rect(center=DARK_BTN.center))

# 当前水果
cur_label      = ""
cur_sprite     = None
cur_conf       = 0.0
last_label_disp = ""
last_conf_disp  = 0.0

# 袋子
bag_count    = 0
bag_sprite   = None

# 动画
flying      = []
particles   = []
bag_shake   = BagShake()
ok_button   = OKButton()
done_parts  = []

detect_cooldown = 0.0

click_pending  = 0
click_timer    = 0.0
CLICK_INTERVAL = 0.18

# ════════════════════════════════
#  ASK 界面
# ════════════════════════════════
class AskDialog:
    def __init__(self, label, sprite_key, conf):
        self.label      = label
        self.sprite_key = sprite_key
        self.conf       = conf
        self.btn_one  = pygame.Rect(640, 440, 160, 56)
        self.btn_many = pygame.Rect(820, 440, 160, 56)
        self.btn_skip = pygame.Rect(730, 510, 130, 40)
        self.choice   = None
        self.pulse    = 0.0

    def update(self, dt):
        self.pulse += dt * 4

    def draw(self, surf, mp):
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 110))
        surf.blit(ov, (0, 0))
        box = pygame.Rect(590, 300, 420, 280)
        pygame.draw.rect(surf, WHITE, box, border_radius=18)
        pygame.draw.rect(surf, ORANGE_C, box, 3, border_radius=18)
        if self.sprite_key in sprites:
            icon = pygame.transform.scale(sprites[self.sprite_key], (56, 56))
            surf.blit(icon, (box.centerx - 28, box.y + 18))
        name_surf = font_large.render(self.label.replace("_"," ").title(), True, BLACK)
        surf.blit(name_surf, name_surf.get_rect(centerx=box.centerx, top=box.y+82))
        conf_surf = font_medium.render(f"置信度 {self.conf:.0%}", True, DARK_GRAY)
        surf.blit(conf_surf, conf_surf.get_rect(centerx=box.centerx, top=box.y+114))
        q_surf = font_large.render("加几个？", True, BLACK)
        surf.blit(q_surf, q_surf.get_rect(centerx=box.centerx, top=box.y+148))
        c1 = (40,190,40) if self.btn_one.collidepoint(mp) else GREEN
        pygame.draw.rect(surf, c1, self.btn_one, border_radius=12)
        pygame.draw.rect(surf, (20,120,20), self.btn_one, 2, border_radius=12)
        t1 = font_large.render("1 个", True, WHITE)
        surf.blit(t1, t1.get_rect(center=self.btn_one.center))
        cm = (220,120,20) if self.btn_many.collidepoint(mp) else (255,160,30)
        pygame.draw.rect(surf, cm, self.btn_many, border_radius=12)
        pygame.draw.rect(surf, (180,90,0), self.btn_many, 2, border_radius=12)
        tm = font_large.render("多 个", True, WHITE)
        surf.blit(tm, tm.get_rect(center=self.btn_many.center))
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

# ═══════════════════════════════════
#  NEW: 绘制底部选项卡
# ═══════════════════════════════════

def draw_tabs(surf, mp):
    total_w = len(TABS) * (TAB_W + 8)
    start_x = W // 2 - total_w // 2
    for i, tab in enumerate(TABS):
        tx = start_x + i * (TAB_W + 8)
        rect = pygame.Rect(tx, TAB_Y, TAB_W, TAB_H)
        is_active = (tab == current_tab)
        is_hovered = rect.collidepoint(mp)

        if is_active:
            col = ORANGE_C
        elif is_hovered:
            col = theme.lerp_color((200, 200, 210), (80, 80, 100))
        else:
            col = theme.lerp_color((170, 170, 180), (60, 60, 75))

        pygame.draw.rect(surf, col, rect, border_radius=8)
        text_col = WHITE if is_active else theme.text
        ts = font_small.render(TAB_LABELS[tab], True, text_col)
        surf.blit(ts, ts.get_rect(center=rect.center))

    return start_x, total_w

def handle_tab_click(pos):
    global current_tab
    total_w = len(TABS) * (TAB_W + 8)
    start_x = W // 2 - total_w // 2
    for i, tab in enumerate(TABS):
        tx = start_x + i * (TAB_W + 8)
        rect = pygame.Rect(tx, TAB_Y, TAB_W, TAB_H)
        if rect.collidepoint(pos):
            current_tab = tab
            return True
    return False


# ════════════════════════════════
#  主循环
# ════════════════════════════════
running = True
dt = 0.0
cam_frame_latest = None
fridge_hovered_idx = -1

while running:
    dt = clock.tick(60) / 1000.0
    mp = pygame.mouse.get_pos()

    # ── 拉取摄像头帧 ──
    if not cv_queue.empty():
        cam_frame_latest = cv_queue.get()

    # ── 主题更新 ──
    theme.update(dt)

    # ── 通知更新 ──
    for n in notifications[:]:
        n.update(dt)
        if n.life <= 0:
            notifications.remove(n)

    # ── 条码模式控制 ──
    if state == STATE_BARCODE:
        _bc_scan_active.set()
    else:
        _bc_scan_active.clear()

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

    if not barcode_result_queue.empty() and barcode_dialog is None:
        code, name = barcode_result_queue.get()
        barcode_dialog = BarcodeDialog(code, name)
        barcode_overlay_rects.clear()

    if barcode_dialog:
        barcode_dialog.update(dt)

    # ── 推理结果 ──
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

    # ── 动画更新 ──
    for fo in flying[:]:
        fo.update(dt)
        if fo.done:
            flying.remove(fo)
            for _ in range(14):
                particles.append(Particle(BAG_X, BAG_Y + 5))
            bag_shake.trigger()

    for p in particles[:]:
        p.update(dt)
        if p.life <= 0: particles.remove(p)
    for p in done_parts[:]:
        p.update(dt)
        if p.life <= 0: done_parts.remove(p)

    bag_shake.update(dt)
    ok_button.update(dt, mp)
    if ask_dialog: ask_dialog.update(dt)

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
    screen.fill(theme.bg)

    # ── 底部选项卡（始终画） ──
    draw_tabs(screen, mp)

    # ── 顶部按钮 ──
    draw_dark_btn(screen, mp)

    if current_tab == "scan":
        # =====================
        #  扫描 Tab
        # =====================

        # 摄像头预览
        screen.blit(font_medium.render("摄像头识别", True, theme.text), (50, 20))
        if cam_frame_latest is not None:
            disp = cv2.cvtColor(cv2.resize(cam_frame_latest,(CAM_W,CAM_H)), cv2.COLOR_BGR2RGB)
            cam_surf = pygame.surfarray.make_surface(np.flipud(np.rot90(disp)))
            screen.blit(cam_surf, (50, 52))

        if state == STATE_BARCODE and cam_frame_latest is not None:
            bc_hint = font_medium.render(
                "🔲 对准条码..." if not barcode_lookup_busy else "⏳ 查询中...",
                True, (50, 120, 220))
            screen.blit(bc_hint, (50, 308))
            for (bx, by, bw, bh) in barcode_overlay_rects:
                sx = int(bx * CAM_W / cam_frame_latest.shape[1]) + 50
                sy = int(by * CAM_H / cam_frame_latest.shape[0]) + 52
                sw = int(bw * CAM_W / cam_frame_latest.shape[1])
                sh = int(bh * CAM_H / cam_frame_latest.shape[0])
                pygame.draw.rect(screen, (50, 220, 50), (sx, sy, sw, sh), 3)

        draw_mode_btn(screen, mp)

        if last_label_disp and state != STATE_BARCODE:
            col = GREEN if last_conf_disp > 0.75 else YELLOW
            screen.blit(font_small.render(f"识别: {last_label_disp}  ({last_conf_disp:.0%})", True, theme.text), (50, 308))

        if state == STATE_IDLE:
            hint = font_medium.render("把食物对准摄像头...", True, theme.text_dim)
            screen.blit(hint, (50, 338))

        if state in (STATE_BAGGING, STATE_DONE) or bag_count > 0:
            screen.blit(font_medium.render("购物袋", True, theme.text), (BAG_X - 30, BAG_Y - 35))
            draw_bag(screen, bag_shake, bag_sprite, bag_count)

        for fo in flying: fo.draw(screen)
        for p in particles: p.draw(screen)

        draw_queue(screen, bag_sprite, bag_count, shopping_queue)

        if state == STATE_BAGGING:
            brect = pygame.Rect(BAG_X-BAG_W//2-12, BAG_Y-25, BAG_W+24, BAG_H+38)
            pw = int(3 + 2*math.sin(time.time()*8))
            pygame.draw.rect(screen, ORANGE_C, brect, pw, border_radius=8)
            arr_y = int(BAG_Y - 46 + 5*math.sin(time.time()*5))
            at = font_large.render("▼ 点击添加", True, ORANGE_C)
            screen.blit(at, at.get_rect(centerx=BAG_X, top=arr_y))

        if bag_count > 0 and state != STATE_DONE:
            ok_button.draw(screen)
            screen.blit(font_small.render("完成 / 随时退出", True, theme.text_dim),
                        (ok_button.rect.centerx - 42, ok_button.rect.bottom + 4))

        if state == STATE_ASK and ask_dialog:
            ask_dialog.draw(screen, mp)

        if barcode_dialog:
            barcode_dialog.draw(screen, mp)

        if state == STATE_DONE:
            for p in done_parts: p.draw(screen)
            banner = pygame.Surface((W, 64), pygame.SRCALPHA)
            banner.fill((30, 160, 30, 210))
            screen.blit(banner, (0, 0))
            bx_off = W // 2 - 80
            if bag_sprite and bag_sprite in sprites:
                big = pygame.transform.scale(sprites[bag_sprite], (44, 44))
                screen.blit(big, (bx_off, 10))
                bx_off += 52
            ct_surf = font_xl.render(f"×{bag_count}  已加入队列！", True, WHITE)
            screen.blit(ct_surf, ct_surf.get_rect(midleft=(bx_off, 32)))
            cont = font_small.render("点击 OK 继续添加  |  ESC 退出", True, (200, 255, 200))
            screen.blit(cont, cont.get_rect(centerx=W//2, top=H - 58))
            ok_button.draw(screen)
            screen.blit(font_small.render("继续添加", True, theme.text_dim),
                        (ok_button.rect.centerx - 30, ok_button.rect.bottom + 4))

    elif current_tab == "fridge":
        # =====================
        #  冰箱 Tab
        # =====================
        screen.blit(font_large.render("🧊 我的冰箱", True, theme.text), (60, 20))

        # 过期提醒
        expired_items = [item for item in fridge_items if get_expiry_status(item)[0] == "expired"]
        warning_items = [item for item in fridge_items if get_expiry_status(item)[0] == "warning"]

        alert_y = 52
        if expired_items:
            alert = font_medium.render(f"❌ {len(expired_items)} 件食物已过期！", True, RED)
            screen.blit(alert, (60, alert_y))
            alert_y += 24
        if warning_items:
            alert = font_medium.render(f"⚠️ {len(warning_items)} 件即将过期", True, YELLOW)
            screen.blit(alert, (60, alert_y))
            alert_y += 24

        if not fridge_items:
            hint = font_medium.render("冰箱空空的~ 去扫描Tab添加食物吧", True, theme.text_dim)
            screen.blit(hint, (60, 120))
        else:
            # 左侧列表视图
            list_x = 50
            list_y = max(alert_y + 10, 80)
            for i, item in enumerate(fridge_items):
                if list_y + i * 42 > TAB_Y - 50:
                    more = font_small.render(f"...还有 {len(fridge_items) - i} 项", True, theme.text_dim)
                    screen.blit(more, (list_x, list_y + i * 42))
                    break

                iy = list_y + i * 42
                row_rect = pygame.Rect(list_x, iy, 340, 38)

                status, days = get_expiry_status(item)
                bg = theme.panel
                if status == "expired": bg = (80, 20, 20) if theme.dark else (255, 210, 210)
                elif status == "warning": bg = (80, 70, 15) if theme.dark else (255, 245, 200)

                pygame.draw.rect(screen, bg, row_rect, border_radius=8)
                pygame.draw.rect(screen, theme.panel_border, row_rect, 1, border_radius=8)

                # 图标
                sk = item.get("sprite_key")
                if sk and sk in sprites:
                    icon = pygame.transform.scale(sprites[sk], (28, 28))
                    screen.blit(icon, (list_x + 6, iy + 5))

                # 名称 + 数量
                name_s = font_medium.render(f"{item['label'].title()} ×{item['count']}", True, theme.text)
                screen.blit(name_s, (list_x + 40, iy + 8))

                # 保质期
                if status == "expired":
                    exp_s = font_small.render("已过期!", True, RED)
                elif status == "warning":
                    exp_s = font_small.render(f"剩{days}天", True, (200, 140, 0))
                else:
                    exp_s = font_small.render(f"剩{days}天", True, theme.text_dim)
                screen.blit(exp_s, (list_x + 260, iy + 10))

                # 删除按钮
                del_rect = pygame.Rect(row_rect.right - 32, iy + 6, 26, 26)
                del_hov = del_rect.collidepoint(mp)
                pygame.draw.rect(screen, (220, 60, 60) if del_hov else theme.text_dim,
                                 del_rect, border_radius=6)
                ds = font_small.render("✕", True, WHITE)
                screen.blit(ds, ds.get_rect(center=del_rect.center))

        # 右侧简易冰箱图
        # (simple visual — just draw the fridge shelf view)
        draw_fridge(screen, mp)

    elif current_tab == "recipes":
        # =====================
        #  食谱 Tab
        # =====================
        draw_recipes_tab(screen, mp)

    elif current_tab == "stats":
        # =====================
        #  统计 Tab
        # =====================
        draw_stats_tab(screen, mp)

    # ── 通知绘制（所有 Tab 之上） ──
    for i, n in enumerate(notifications):
        n.draw(screen, i * 44)

    pygame.display.update()

    # ════ 事件 ════
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False

        if event.type == pygame.MOUSEBUTTONDOWN:
            # 选项卡点击
            if handle_tab_click(event.pos):
                continue

            # 暗色按钮
            if DARK_BTN.collidepoint(event.pos):
                theme.toggle()
                continue

            # 冰箱Tab：删除按钮
            if current_tab == "fridge":
                list_x = 50
                alert_y_calc = 52
                expired_items = [item for item in fridge_items if get_expiry_status(item)[0] == "expired"]
                warning_items = [item for item in fridge_items if get_expiry_status(item)[0] == "warning"]
                if expired_items: alert_y_calc += 24
                if warning_items: alert_y_calc += 24
                list_y = max(alert_y_calc + 10, 80)

                for i, item in enumerate(fridge_items):
                    iy = list_y + i * 42
                    row_rect = pygame.Rect(list_x, iy, 340, 38)
                    del_rect = pygame.Rect(row_rect.right - 32, iy + 6, 26, 26)
                    if del_rect.collidepoint(event.pos):
                        removed = fridge_items[i]
                        remove_from_fridge(i)
                        add_notification(f"已移除 {removed['label'].title()}", RED)
                        break

            # 扫描Tab逻辑
            if current_tab == "scan":
                # 模式切换按钮
                if MODE_BTN.collidepoint(event.pos):
                    if state == STATE_BARCODE:
                        state = STATE_IDLE
                        barcode_overlay_rects.clear()
                        barcode_dialog   = None
                        barcode_cooldown = 0.0
                        _bc_scan_active.clear()
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

                # 加入购物队列
                merged = False
                for i, entry in enumerate(shopping_queue):
                    sk = entry[0]; cnt = entry[1]
                    lbl = entry[2] if len(entry) > 2 else ""
                    if lbl == bname or sk == bsprite and lbl == bname:
                        shopping_queue[i] = (sk, cnt + bcount, lbl)
                        merged = True; break
                if not merged:
                    shopping_queue.append((bsprite, bcount, bname))

                # NEW: 同时加入冰箱
                add_to_fridge(bname, bsprite, bcount, "other")
                add_notification(f"✓ {bname} ×{bcount} 已加入冰箱")

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
                bag_sprite = cur_sprite
                flying.append(FlyingFruit(cur_sprite, 380, 180, BAG_X, BAG_Y+8))
                bag_count += 1
                state = STATE_BAGGING
                ask_dialog = None; detect_cooldown = 1.2
            elif ask_dialog.choice == "many":
                bag_sprite = cur_sprite
                state = STATE_BAGGING
                ask_dialog = None; detect_cooldown = 1.2
            elif ask_dialog.choice == "skip":
                state = STATE_IDLE
                ask_dialog = None; detect_cooldown = 1.5

        # BAGGING：点击袋子
        if state == STATE_BAGGING and event.type == pygame.MOUSEBUTTONDOWN and current_tab == "scan":
            brect = pygame.Rect(BAG_X-BAG_W//2-15, BAG_Y-30, BAG_W+30, BAG_H+45)
            if brect.collidepoint(event.pos):
                if not flying:
                    flying.append(FlyingFruit(cur_sprite,
                        380+random.randint(-20,20), 180+random.randint(-25,25),
                        BAG_X, BAG_Y+8))
                    bag_count += 1
                else:
                    click_pending += 1
                    if click_timer <= 0:
                        click_timer = CLICK_INTERVAL

        # OK 按钮
        ok_button.handle(event)
        if ok_button.clicked:
            ok_button.clicked = False
            if state == STATE_DONE:
                # 加入购物队列
                merged = False
                for i, entry in enumerate(shopping_queue):
                    if entry[0] == bag_sprite and (len(entry) < 3 or entry[2] == ""):
                        shopping_queue[i] = (entry[0], entry[1] + bag_count, "")
                        merged = True; break
                if not merged:
                    shopping_queue.append((bag_sprite, bag_count, ""))

                # NEW: 同时加入冰箱
                add_to_fridge(cur_label, bag_sprite, bag_count)
                add_notification(f"✓ {cur_label.title()} ×{bag_count} 已存入冰箱！")

                bag_count = 0; bag_sprite = None
                flying.clear(); particles.clear(); done_parts.clear()
                click_pending = 0; detect_cooldown = 1.0
                state = STATE_IDLE
            elif bag_count > 0:
                state = STATE_DONE
                click_pending = 0
                for _ in range(65):
                    p = Particle(W//2, H//2, explode=True)
                    done_parts.append(p)

pygame.quit()
exit()