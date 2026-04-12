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
import heapq
from datetime import datetime, timedelta

# ════════════════════════════════
#  OpenAI API — 估算过期日期
# ════════════════════════════════
# 在环境变量或这里设置你的 OpenAI API key
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
FRIDGE_TEMP_C  = 8   # 冰箱温度（摄氏度）

def estimate_shelf_life_openai(food_name, callback):
    """
    调用 OpenAI API 估算食物在 FRIDGE_TEMP_C°C 冰箱中的保质天数。
    callback(food_name, days, explanation) 在结果返回时被调用。
    """
    try:
        prompt = (
            f"You are a food safety expert. "
            f"Estimate how many days '{food_name}' (fresh, uncut, store-bought) "
            f"can be safely stored in a refrigerator at {FRIDGE_TEMP_C}°C before it spoils. "
            f"Respond ONLY in valid JSON with exactly two keys:\n"
            f'  "days": <integer>,\n'
            f'  "explanation": "<one sentence explaining why>"\n'
            f"No markdown, no extra text."
        )

        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 120,
            "temperature": 0.2,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        text = data["choices"][0]["message"]["content"].strip()
        # 清理可能的 markdown 代码块
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        result = json.loads(text)
        days = int(result.get("days", 7))
        explanation = result.get("explanation", "")
        callback(food_name, days, explanation)

    except Exception as e:
        print(f"[OpenAI] 估算失败 ({food_name}): {e}")
        # 使用本地 fallback
        days, explanation = _local_shelf_life(food_name)
        callback(food_name, days, explanation)


# ── 本地 fallback（无网络 / API 失败时使用）──
_LOCAL_SHELF = {
    "apple": (28, "Apples keep well refrigerated for about 4 weeks."),
    "banana": (5, "Bananas brown quickly; 8°C slows but doesn't prevent it."),
    "carrot": (21, "Carrots stay crisp for ~3 weeks in the fridge."),
    "cucumber": (7, "Cucumbers are chill-sensitive; about 1 week at 8°C."),
    "eggplant": (7, "Eggplant lasts ~1 week refrigerated."),
    "garlic": (60, "Whole garlic keeps for months; ~2 months refrigerated."),
    "grapes": (10, "Grapes last about 10 days in the fridge."),
    "kiwi": (21, "Ripe kiwi lasts ~3 weeks refrigerated."),
    "lemon": (21, "Lemons keep well for about 3 weeks."),
    "mango": (7, "Ripe mangoes last about 5–7 days in the fridge."),
    "onion": (30, "Onions store well for ~1 month refrigerated."),
    "orange": (21, "Oranges last about 3 weeks in the fridge."),
    "pear": (10, "Pears ripen then last ~10 days refrigerated."),
    "pineapple": (5, "Cut pineapple lasts ~5 days; whole ~7 days."),
    "potato": (21, "Potatoes can last 2–3 weeks at 8°C (watch for sprouting)."),
    "strawberry": (5, "Strawberries are very perishable; ~5 days max."),
    "tomato": (7, "Tomatoes last ~1 week; flavor degrades below 12°C."),
    "watermelon": (7, "Cut watermelon lasts ~5–7 days refrigerated."),
    "corn": (5, "Fresh corn loses sweetness fast; use within 5 days."),
    "peach": (5, "Peaches are delicate; ~5 days refrigerated."),
    "cherry": (7, "Cherries last about 1 week in the fridge."),
    "ginger": (21, "Fresh ginger root keeps ~3 weeks refrigerated."),
    "cabbage": (14, "Cabbage stays good for ~2 weeks."),
    "bell pepper": (10, "Bell peppers last about 10 days refrigerated."),
    "pomegranate": (30, "Whole pomegranates last ~1 month in the fridge."),
}

def _local_shelf_life(food_name):
    key = food_name.lower().strip()
    if key in _LOCAL_SHELF:
        return _LOCAL_SHELF[key]
    # 尝试部分匹配
    for k, v in _LOCAL_SHELF.items():
        if k in key or key in k:
            return v
    return (7, f"Default estimate: ~7 days at {FRIDGE_TEMP_C}°C.")


# ════════════════════════════════
#  Priority Queue（按过期日期排序）
# ════════════════════════════════
class FridgePriorityQueue:
    """
    基于 heapq 的优先队列，comparator 是过期日期（越早过期越靠前）。
    每个元素: (expiry_date, insert_order, item_dict)
    item_dict = {
        "name": str,
        "sprite_key": str,
        "count": int,
        "added_date": datetime,
        "expiry_date": datetime,
        "shelf_days": int,
        "explanation": str,
        "barcode": str or "",   # 条码商品才有
    }
    """

    def __init__(self):
        self._heap = []
        self._counter = 0   # 打破相同过期日期的 tie

    def push(self, item_dict):
        expiry = item_dict["expiry_date"]
        self._counter += 1
        heapq.heappush(self._heap, (expiry, self._counter, item_dict))

    def pop(self):
        if self._heap:
            expiry, _, item = heapq.heappop(self._heap)
            return item
        return None

    def peek(self):
        if self._heap:
            return self._heap[0][2]
        return None

    def remove_by_name(self, name):
        """移除第一个匹配名称的元素"""
        for i, (exp, cnt, item) in enumerate(self._heap):
            if item["name"] == name:
                self._heap.pop(i)
                heapq.heapify(self._heap)
                return item
        return None

    def all_items(self):
        """返回按过期日期排序的所有元素（不消费）"""
        return [item for (_, _, item) in sorted(self._heap)]

    def __len__(self):
        return len(self._heap)

    def __bool__(self):
        return len(self._heap) > 0


# ════════════════════════════════
#  全局 PQ 实例
# ════════════════════════════════
fridge_pq = FridgePriorityQueue()

# 待处理的 OpenAI 回调队列（线程安全 → 主线程消费）
_shelf_result_queue = queue.Queue()

def _on_shelf_estimated(food_name, days, explanation):
    """OpenAI 线程回调：结果放入队列，主线程读取"""
    _shelf_result_queue.put((food_name, days, explanation))

# 等待 shelf life 估算的暂存区
# key=food_name, value=dict (partial item waiting for days/explanation)
_pending_shelf = {}


# pyzbar 可选依赖：pip install pyzbar
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
pygame.display.set_caption("FridgeBud — Priority Queue Edition")
clock = pygame.time.Clock()
font_large  = pygame.font.Font(None, 32)
font_medium = pygame.font.Font(None, 24)
font_small  = pygame.font.Font(None, 20)
font_tiny   = pygame.font.Font(None, 17)
font_xl     = pygame.font.Font(None, 72)
font_xxl    = pygame.font.Font(None, 110)
font_huge   = pygame.font.Font(None, 140)

# ── Sprites ──
SPRITE_PATH = r"/home/pi/myenv/Free_pixel_food_16x16\Icons"
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
BLUE       = (50,  100, 200)
LIGHT_BLUE = (200, 220, 255)
URGENT_RED = (255, 60,  60 )
WARN_ORANGE= (255, 165, 0  )
SAFE_GREEN = (60,  180, 60 )

# ── Bag params ──
BAG_X, BAG_Y = 820, 390
BAG_W, BAG_H = 160, 185

# ════════════════════════════════
#  物理动画类（与原版一致）
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


# ════════════════════════════════
#  Priority Queue 面板绘制
# ════════════════════════════════
PQ_PANEL_X = 400
PQ_PANEL_Y = 52
PQ_PANEL_W = 380
PQ_PANEL_H = 280
PQ_SCROLL_OFFSET = 0   # 滚动偏移

def draw_pq_panel(surf, pq, mp):
    """绘制冰箱优先队列面板（右侧）"""
    global PQ_SCROLL_OFFSET

    # 面板背景
    panel = pygame.Rect(PQ_PANEL_X, PQ_PANEL_Y, PQ_PANEL_W, PQ_PANEL_H)
    pygame.draw.rect(surf, (245, 248, 255), panel, border_radius=12)
    pygame.draw.rect(surf, BLUE, panel, 2, border_radius=12)

    # 标题栏
    title_rect = pygame.Rect(PQ_PANEL_X, PQ_PANEL_Y, PQ_PANEL_W, 34)
    pygame.draw.rect(surf, (50, 100, 200), title_rect, border_radius=12)
    pygame.draw.rect(surf, (50, 100, 200),
                     pygame.Rect(PQ_PANEL_X, PQ_PANEL_Y + 16, PQ_PANEL_W, 18))
    title = font_medium.render(f"🧊 冰箱 ({FRIDGE_TEMP_C}°C) — 过期优先队列", True, WHITE)
    surf.blit(title, title.get_rect(centerx=panel.centerx, centery=title_rect.centery))

    items = pq.all_items()
    if not items:
        empty = font_medium.render("空 — 添加食物后自动排序", True, DARK_GRAY)
        surf.blit(empty, empty.get_rect(center=panel.center))
        return

    now = datetime.now()
    row_h = 48
    visible_rows = (PQ_PANEL_H - 40) // row_h
    max_scroll = max(0, len(items) - visible_rows)
    PQ_SCROLL_OFFSET = min(PQ_SCROLL_OFFSET, max_scroll)

    # 裁剪区域
    clip = pygame.Rect(PQ_PANEL_X + 4, PQ_PANEL_Y + 36, PQ_PANEL_W - 8, PQ_PANEL_H - 40)
    surf.set_clip(clip)

    for idx, item in enumerate(items):
        if idx < PQ_SCROLL_OFFSET:
            continue
        vis_idx = idx - PQ_SCROLL_OFFSET
        if vis_idx >= visible_rows + 1:
            break

        ry = PQ_PANEL_Y + 38 + vis_idx * row_h
        row_rect = pygame.Rect(PQ_PANEL_X + 6, ry, PQ_PANEL_W - 12, row_h - 4)

        # 过期状态颜色
        days_left = (item["expiry_date"] - now).days
        if days_left < 0:
            bg_col = (255, 200, 200)   # 已过期
            status_col = URGENT_RED
            status_txt = f"已过期 {-days_left}天!"
        elif days_left <= 2:
            bg_col = (255, 230, 200)
            status_col = WARN_ORANGE
            status_txt = f"剩 {days_left}天!"
        elif days_left <= 5:
            bg_col = (255, 245, 210)
            status_col = ORANGE_C
            status_txt = f"剩 {days_left}天"
        else:
            bg_col = (220, 245, 220)
            status_col = SAFE_GREEN
            status_txt = f"剩 {days_left}天"

        pygame.draw.rect(surf, bg_col, row_rect, border_radius=8)
        pygame.draw.rect(surf, (180, 180, 190), row_rect, 1, border_radius=8)

        # 排名标号
        rank = font_medium.render(f"#{idx+1}", True, DARK_GRAY)
        surf.blit(rank, (row_rect.x + 6, row_rect.y + 14))

        # 图标
        sk = item.get("sprite_key")
        if sk and sk in sprites:
            icon = pygame.transform.scale(sprites[sk], (28, 28))
            surf.blit(icon, (row_rect.x + 38, row_rect.y + 8))

        # 名称 + 数量
        disp_name = item["name"].replace("_", " ").title()
        if len(disp_name) > 12:
            disp_name = disp_name[:11] + "…"
        name_s = font_medium.render(f"{disp_name} ×{item['count']}", True, BLACK)
        surf.blit(name_s, (row_rect.x + 72, row_rect.y + 4))

        # 过期日期 + 状态
        exp_str = item["expiry_date"].strftime("%m/%d")
        exp_s = font_small.render(f"到期: {exp_str}", True, DARK_GRAY)
        surf.blit(exp_s, (row_rect.x + 72, row_rect.y + 26))

        status_s = font_small.render(status_txt, True, status_col)
        surf.blit(status_s, (row_rect.right - status_s.get_width() - 8, row_rect.y + 14))

        # 悬停时显示 explanation tooltip
        if row_rect.collidepoint(mp) and item.get("explanation"):
            _draw_tooltip(surf, mp[0], mp[1], item["explanation"])

    surf.set_clip(None)

    # 滚动指示
    if len(items) > visible_rows:
        if PQ_SCROLL_OFFSET > 0:
            arr = font_small.render("▲ 上滚", True, BLUE)
            surf.blit(arr, (panel.right - 60, panel.y + 38))
        if PQ_SCROLL_OFFSET < max_scroll:
            arr = font_small.render("▼ 下滚", True, BLUE)
            surf.blit(arr, (panel.right - 60, panel.bottom - 16))


def _draw_tooltip(surf, mx, my, text):
    """在鼠标旁画 tooltip"""
    max_w = 240
    words = text.split()
    lines = []
    line = ""
    for w in words:
        test = line + " " + w if line else w
        if font_tiny.size(test)[0] > max_w:
            if line: lines.append(line)
            line = w
        else:
            line = test
    if line: lines.append(line)

    lh = 16
    tw = max(font_tiny.size(l)[0] for l in lines) + 16
    th = len(lines) * lh + 12

    tx = min(mx + 14, W - tw - 4)
    ty = max(my - th - 6, 4)

    tip_surf = pygame.Surface((tw, th), pygame.SRCALPHA)
    tip_surf.fill((40, 40, 40, 220))
    pygame.draw.rect(tip_surf, (80, 80, 80, 220), (0, 0, tw, th), 1, border_radius=6)
    for i, l in enumerate(lines):
        ls = font_tiny.render(l, True, WHITE)
        tip_surf.blit(ls, (8, 6 + i * lh))
    surf.blit(tip_surf, (tx, ty))


# ── Queue display (bottom strip) ──
shopping_queue = []

def draw_queue(surf, fruit_key, bag_cnt, queue_list):
    qx, qy = 50, 618
    surf.blit(font_medium.render("购物队列:", True, BLACK), (qx, qy))
    if queue_list:
        ix = qx + 75
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
                ls = font_small.render(short, True, DARK_GRAY)
                surf.blit(ls, (ix, qy - 18))
            ix += 100
    else:
        surf.blit(font_medium.render("—", True, DARK_GRAY), (qx + 75, qy))


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

# ── 条码相关 ──
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
        at = font_large.render("加入冰箱", True, WHITE)
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
MODE_BTN = pygame.Rect(W - 200, 14, 185, 38)
def draw_mode_btn(surf, mp):
    is_bc = state == STATE_BARCODE
    col   = (50, 120, 220) if is_bc else (80, 80, 80)
    hov   = MODE_BTN.collidepoint(mp)
    if hov: col = tuple(min(255, c+30) for c in col)
    pygame.draw.rect(surf, col, MODE_BTN, border_radius=10)
    label = "📸 摄像头识别" if is_bc else "🔲 扫条码"
    ls = font_medium.render(label, True, WHITE)
    surf.blit(ls, ls.get_rect(center=MODE_BTN.center))


# ── 当前水果 ──
cur_label      = ""
cur_sprite     = None
cur_conf       = 0.0
last_label_disp = ""
last_conf_disp  = 0.0

bag_count    = 0
bag_sprite   = None
shopping_queue = []

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
#  ASK 对话框
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


# ════════════════════════════════
#  辅助：将食物加入 PQ（带 OpenAI 估算）
# ════════════════════════════════
def add_to_fridge_pq(name, sprite_key, count, barcode=""):
    """
    添加食物到冰箱优先队列。
    先启动 OpenAI 线程估算 shelf life，结果回来后再 push 到 PQ。
    """
    pending_key = f"{name}_{time.time()}"
    _pending_shelf[pending_key] = {
        "name": name,
        "sprite_key": sprite_key,
        "count": count,
        "barcode": barcode,
        "added_date": datetime.now(),
    }

    def _cb(food_name, days, explanation):
        _shelf_result_queue.put((pending_key, days, explanation))

    threading.Thread(
        target=estimate_shelf_life_openai,
        args=(name, _cb),
        daemon=True
    ).start()


def process_shelf_results():
    """主线程每帧调用：消费 OpenAI 回调，创建 PQ 条目"""
    while not _shelf_result_queue.empty():
        try:
            pending_key, days, explanation = _shelf_result_queue.get_nowait()
        except queue.Empty:
            break

        if pending_key not in _pending_shelf:
            continue

        info = _pending_shelf.pop(pending_key)
        expiry = info["added_date"] + timedelta(days=days)

        item_dict = {
            "name": info["name"],
            "sprite_key": info["sprite_key"],
            "count": info["count"],
            "added_date": info["added_date"],
            "expiry_date": expiry,
            "shelf_days": days,
            "explanation": explanation,
            "barcode": info.get("barcode", ""),
        }
        fridge_pq.push(item_dict)
        print(f"[PQ] 已加入: {info['name']} ×{info['count']}, "
              f"保质 {days}天, 到期 {expiry.strftime('%Y-%m-%d')}")


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

    # ── 拉取推理结果 ──
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

    # ── 处理 OpenAI shelf life 回调 ──
    process_shelf_results()

    # ── 更新动画 ──
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

    # ── 连续点击飞出 ──
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

    # 条码模式覆盖
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

    # ── 优先队列面板（始终显示）──
    draw_pq_panel(screen, fridge_pq, mp)

    # 温度指示器
    temp_txt = font_medium.render(f"🌡 {FRIDGE_TEMP_C}°C", True, BLUE)
    screen.blit(temp_txt, (PQ_PANEL_X + PQ_PANEL_W - 62, PQ_PANEL_Y - 22))

    # 袋子
    if state in (STATE_BAGGING, STATE_DONE) or bag_count > 0:
        screen.blit(font_medium.render("购物袋", True, BLACK), (BAG_X - 30, BAG_Y - 35))
        draw_bag(screen, bag_shake, bag_sprite, bag_count)

    # 飞行动画
    for fo in flying: fo.draw(screen)
    for p in particles: p.draw(screen)

    # 队列底栏
    draw_queue(screen, bag_sprite, bag_count, shopping_queue)

    # BAGGING 提示
    if state == STATE_BAGGING:
        brect = pygame.Rect(BAG_X-BAG_W//2-12, BAG_Y-25, BAG_W+24, BAG_H+38)
        pw = int(3 + 2*math.sin(time.time()*8))
        pygame.draw.rect(screen, ORANGE_C, brect, pw, border_radius=8)
        arr_y = int(BAG_Y - 46 + 5*math.sin(time.time()*5))
        at = font_large.render("▼ 点击添加", True, ORANGE_C)
        screen.blit(at, at.get_rect(centerx=BAG_X, top=arr_y))

    # OK 按钮
    if bag_count > 0 and state != STATE_DONE:
        ok_button.draw(screen)
        screen.blit(font_small.render("完成 / 随时退出", True, DARK_GRAY),
                    (ok_button.rect.centerx - 42, ok_button.rect.bottom + 4))

    # ASK 对话框
    if state == STATE_ASK and ask_dialog:
        ask_dialog.draw(screen, mp)

    # 条码对话框
    if barcode_dialog:
        barcode_dialog.draw(screen, mp)

    # DONE 状态
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
        ct_surf = font_xl.render(f"×{bag_count}  已加入冰箱！", True, WHITE)
        screen.blit(ct_surf, ct_surf.get_rect(midleft=(bx_off, 32)))
        cont = font_small.render("点击 OK 继续添加  |  ESC 退出", True, (200, 255, 200))
        screen.blit(cont, cont.get_rect(centerx=W//2, top=H - 22))
        ok_button.draw(screen)
        screen.blit(font_small.render("继续添加", True, DARK_GRAY),
                    (ok_button.rect.centerx - 30, ok_button.rect.bottom + 4))

    # ── pending shelf 估算的 loading 指示 ──
    if _pending_shelf:
        loading = font_small.render(
            f"⏳ 正在估算 {len(_pending_shelf)} 个商品的保质期...", True, BLUE)
        screen.blit(loading, (PQ_PANEL_X, PQ_PANEL_Y + PQ_PANEL_H + 8))

    pygame.display.update()

    # ════ 事件 ════
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False

        # PQ 面板滚动
        if event.type == pygame.MOUSEWHEEL:
            pq_panel_rect = pygame.Rect(PQ_PANEL_X, PQ_PANEL_Y, PQ_PANEL_W, PQ_PANEL_H)
            if pq_panel_rect.collidepoint(mp):
                PQ_SCROLL_OFFSET = max(0, PQ_SCROLL_OFFSET - event.y)

        # 模式切换
        if event.type == pygame.MOUSEBUTTONDOWN:
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

                # ★ 加入冰箱优先队列（通过 OpenAI 估算过期日期）
                add_to_fridge_pq(bname, bsprite, bcount, barcode=bcode)

                # 也加入购物队列底栏
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
        if state == STATE_BAGGING and event.type == pygame.MOUSEBUTTONDOWN:
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
                # "继续"：把当前袋子存入队列 + PQ，重置
                merged = False
                for i, entry in enumerate(shopping_queue):
                    if entry[0] == bag_sprite and (len(entry) < 3 or entry[2] == ""):
                        shopping_queue[i] = (entry[0], entry[1] + bag_count, "")
                        merged = True; break
                if not merged:
                    shopping_queue.append((bag_sprite, bag_count, ""))

                # ★ 加入冰箱优先队列
                add_to_fridge_pq(cur_label, bag_sprite, bag_count)

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