"""
FridgeBud v2.0 — Enhanced Edition
• SQLite 持久化存储（重启不丢数据）
• 菜单配方管理（录入/查看）
• 自动计算可做份数
• 消耗预测 + 采购方案
• 全新 UI（深色主题 + 霓虹风格）
"""

import pygame
import os
import cv2
import torch
import torchvision.transforms as transforms
from transformers import AutoModelForImageClassification
import threading
import queue
import numpy as np
import math
import random
import time
import urllib.request
import json
import heapq
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════
#  配置
# ═══════════════════════════════════════
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
FRIDGE_TEMP_C  = 8
DB_PATH        = Path(__file__).parent.parent / "fridgebud.db"
SPRITE_PATH    = Path(__file__).parent.parent / "FreePixelFood" / "Assets" / "FreePixelFood" / "Sprite" / "Food"

# ═══════════════════════════════════════
#  数据库层
# ═══════════════════════════════════════
class FridgeDB:
    def __init__(self, path=DB_PATH):
        self.path = str(path)
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS fridge_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                sprite_key  TEXT,
                count       INTEGER DEFAULT 1,
                added_date  TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                shelf_days  INTEGER,
                explanation TEXT,
                barcode     TEXT DEFAULT '',
                consumed    INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS recipes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                servings    INTEGER DEFAULT 1,
                description TEXT,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recipe_ingredients (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id   INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                ingredient  TEXT NOT NULL,
                amount      REAL NOT NULL,
                unit        TEXT DEFAULT 'pcs'
            );
            CREATE TABLE IF NOT EXISTS consumption_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name   TEXT NOT NULL,
                quantity    INTEGER NOT NULL,
                logged_at   TEXT NOT NULL
            );
            """)

    # ── Fridge Items ──
    def save_item(self, item: dict) -> int:
        with self._conn() as c:
            cur = c.execute("""
                INSERT INTO fridge_items (name, sprite_key, count, added_date, expiry_date,
                    shelf_days, explanation, barcode)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                item["name"], item.get("sprite_key",""),
                item["count"],
                item["added_date"].isoformat(),
                item["expiry_date"].isoformat(),
                item.get("shelf_days", 7),
                item.get("explanation",""),
                item.get("barcode",""),
            ))
            return cur.lastrowid

    def update_item_count(self, item_id: int, delta: int):
        with self._conn() as c:
            c.execute("UPDATE fridge_items SET count = MAX(0, count + ?) WHERE id=?", (delta, item_id))

    def remove_item(self, item_id: int):
        with self._conn() as c:
            c.execute("DELETE FROM fridge_items WHERE id=?", (item_id,))

    def log_consumption(self, name: str, qty: int):
        with self._conn() as c:
            c.execute("INSERT INTO consumption_log (item_name, quantity, logged_at) VALUES (?,?,?)",
                      (name, qty, datetime.now().isoformat()))

    def load_fridge(self) -> list:
        with self._conn() as c:
            rows = c.execute("""SELECT * FROM fridge_items WHERE count > 0
                                ORDER BY expiry_date ASC""").fetchall()
            items = []
            for r in rows:
                items.append({
                    "id":          r["id"],
                    "name":        r["name"],
                    "sprite_key":  r["sprite_key"],
                    "count":       r["count"],
                    "added_date":  datetime.fromisoformat(r["added_date"]),
                    "expiry_date": datetime.fromisoformat(r["expiry_date"]),
                    "shelf_days":  r["shelf_days"],
                    "explanation": r["explanation"],
                    "barcode":     r["barcode"],
                })
            return items

    # ── Recipes ──
    def save_recipe(self, name: str, servings: int, description: str, ingredients: list) -> int:
        with self._conn() as c:
            # upsert
            cur = c.execute("""
                INSERT INTO recipes (name, servings, description, created_at)
                VALUES (?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET servings=excluded.servings,
                    description=excluded.description
            """, (name, servings, description, datetime.now().isoformat()))
            rid = cur.lastrowid
            if rid == 0:  # update case
                row = c.execute("SELECT id FROM recipes WHERE name=?", (name,)).fetchone()
                rid = row["id"]
            c.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
            for ing in ingredients:
                c.execute("INSERT INTO recipe_ingredients (recipe_id, ingredient, amount, unit) VALUES (?,?,?,?)",
                          (rid, ing["ingredient"], ing["amount"], ing.get("unit","pcs")))
            return rid

    def load_recipes(self) -> list:
        with self._conn() as c:
            recipes = c.execute("SELECT * FROM recipes ORDER BY name ASC").fetchall()
            result = []
            for r in recipes:
                ings = c.execute("SELECT * FROM recipe_ingredients WHERE recipe_id=?", (r["id"],)).fetchall()
                result.append({
                    "id": r["id"], "name": r["name"],
                    "servings": r["servings"], "description": r["description"],
                    "ingredients": [{"ingredient": i["ingredient"], "amount": i["amount"],
                                     "unit": i["unit"]} for i in ings]
                })
            return result

    def delete_recipe(self, recipe_id: int):
        with self._conn() as c:
            c.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))

    # ── Analytics ──
    def consumption_rate(self, food_name: str, days=30) -> float:
        """平均每天消耗量（件/天）"""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        with self._conn() as c:
            row = c.execute("""SELECT SUM(quantity) FROM consumption_log
                               WHERE item_name LIKE ? AND logged_at > ?""",
                            (f"%{food_name}%", since)).fetchone()
            total = row[0] or 0
        return total / days if days > 0 else 0

    def get_expiry_soon(self, within_days=3) -> list:
        cutoff = (datetime.now() + timedelta(days=within_days)).isoformat()
        with self._conn() as c:
            rows = c.execute("""SELECT name, SUM(count) as total, MIN(expiry_date) as earliest
                                FROM fridge_items WHERE count>0 AND expiry_date<=?
                                GROUP BY name ORDER BY earliest ASC""", (cutoff,)).fetchall()
            return [dict(r) for r in rows]


db = FridgeDB()

# ═══════════════════════════════════════
#  Priority Queue（内存中，从DB加载）
# ═══════════════════════════════════════
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

    def remove_by_id(self, item_id):
        for i, (_, _, item) in enumerate(self._heap):
            if item.get("id") == item_id:
                self._heap.pop(i)
                heapq.heapify(self._heap)
                return item
        return None

    def remove_by_name(self, name):
        for i, (_, _, item) in enumerate(self._heap):
            if item["name"] == name:
                self._heap.pop(i)
                heapq.heapify(self._heap)
                return item
        return None

    def all_items(self):
        return [item for (_, _, item) in sorted(self._heap)]

    def __len__(self): return len(self._heap)
    def __bool__(self): return len(self._heap) > 0


fridge_pq = FridgePriorityQueue()

# 从 DB 恢复数据
for _item in db.load_fridge():
    fridge_pq.push(_item)
print(f"[DB] 已恢复 {len(fridge_pq)} 条冰箱记录")

# ═══════════════════════════════════════
#  Shelf-Life（OpenAI + 本地 fallback）
# ═══════════════════════════════════════
_LOCAL_SHELF = {
    "apple": (28, "Apples keep well refrigerated for about 4 weeks."),
    "banana": (5,  "Bananas brown quickly; 8°C slows but doesn't prevent it."),
    "carrot": (21, "Carrots stay crisp for ~3 weeks in the fridge."),
    "cucumber": (7, "Cucumbers are chill-sensitive; about 1 week at 8°C."),
    "eggplant": (7, "Eggplant lasts ~1 week refrigerated."),
    "garlic": (60, "Whole garlic keeps for months; ~2 months refrigerated."),
    "grapes": (10, "Grapes last about 10 days in the fridge."),
    "kiwi": (21, "Ripe kiwi lasts ~3 weeks refrigerated."),
    "lemon": (21, "Lemons keep well for about 3 weeks."),
    "mango": (7,  "Ripe mangoes last about 5–7 days in the fridge."),
    "onion": (30, "Onions store well for ~1 month refrigerated."),
    "orange": (21,"Oranges last about 3 weeks in the fridge."),
    "pear": (10,  "Pears ripen then last ~10 days refrigerated."),
    "pineapple": (5,"Cut pineapple lasts ~5 days; whole ~7 days."),
    "potato": (21, "Potatoes can last 2–3 weeks at 8°C (watch for sprouting)."),
    "strawberry": (5,"Strawberries are very perishable; ~5 days max."),
    "tomato": (7,  "Tomatoes last ~1 week; flavor degrades below 12°C."),
    "watermelon": (7,"Cut watermelon lasts ~5–7 days refrigerated."),
    "corn": (5,    "Fresh corn loses sweetness fast; use within 5 days."),
    "peach": (5,   "Peaches are delicate; ~5 days refrigerated."),
    "cherry": (7,  "Cherries last about 1 week in the fridge."),
    "ginger": (21, "Fresh ginger root keeps ~3 weeks refrigerated."),
    "cabbage": (14,"Cabbage stays good for ~2 weeks."),
    "bell pepper": (10,"Bell peppers last about 10 days refrigerated."),
    "pomegranate": (30,"Whole pomegranates last ~1 month in the fridge."),
    "broccoli": (7,"Broccoli stays fresh about 1 week."),
    "spinach": (5, "Spinach wilts fast; best within 5 days."),
    "celery": (14, "Celery keeps crisp for about 2 weeks."),
    "mushroom": (7,"Mushrooms last about 1 week refrigerated."),
    "egg": (35,    "Eggs stay fresh about 5 weeks in the fridge."),
    "milk": (7,    "Milk stays fresh about 1 week after opening."),
    "cheese": (21, "Hard cheese keeps well for ~3 weeks."),
    "yogurt": (14, "Yogurt stays good for ~2 weeks."),
    "butter": (60, "Butter keeps for ~2 months in the fridge."),
    "chicken": (3, "Raw chicken should be used within 3 days."),
    "beef": (4,    "Raw beef stays safe for ~4 days."),
    "pork": (3,    "Raw pork should be used within 3 days."),
    "fish": (2,    "Fresh fish is best used within 2 days."),
    "shrimp": (2,  "Fresh shrimp stays good for ~2 days."),
    "tofu": (5,    "Opened tofu should be used within 5 days."),
    "lettuce": (7, "Lettuce stays fresh about 1 week."),
    "avocado": (4, "Ripe avocado lasts ~4 days in the fridge."),
    "blueberry": (10,"Blueberries last about 10 days."),
    "raspberry": (3,"Raspberries are very delicate; use within 3 days."),
    "plum": (7,    "Plums last about 1 week refrigerated."),
    "melon": (7,   "Cut melon lasts ~7 days in the fridge."),
    "radish": (14, "Radishes stay crisp for ~2 weeks."),
    "zucchini": (7,"Zucchini lasts about 1 week refrigerated."),
    "asparagus": (5,"Asparagus stays fresh for ~5 days."),
    "leek": (14,   "Leeks last about 2 weeks in the fridge."),
}

def _local_shelf_life(food_name):
    key = food_name.lower().strip()
    if key in _LOCAL_SHELF: return _LOCAL_SHELF[key]
    for k, v in _LOCAL_SHELF.items():
        if k in key or key in k: return v
    return (7, f"Default estimate: ~7 days at {FRIDGE_TEMP_C}°C.")

def estimate_shelf_life_openai(food_name, callback):
    try:
        prompt = (
            f"You are a food safety expert. "
            f"Estimate how many days '{food_name}' (fresh, uncut, store-bought) "
            f"can be safely stored in a refrigerator at {FRIDGE_TEMP_C}°C before it spoils. "
            f'Respond ONLY in valid JSON: {{"days": <int>, "explanation": "<one sentence>"}}'
        )
        payload = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 120, "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {OPENAI_API_KEY}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"].strip()
        if text.startswith("```"): text = text.split("\n",1)[1] if "\n" in text else text[3:]
        if text.endswith("```"): text = text[:-3]
        result = json.loads(text.strip())
        callback(food_name, int(result.get("days",7)), result.get("explanation",""))
    except Exception as e:
        print(f"[OpenAI] fallback ({food_name}): {e}")
        days, explanation = _local_shelf_life(food_name)
        callback(food_name, days, explanation)

_shelf_result_queue = queue.Queue()
_pending_shelf = {}

def _on_shelf_estimated(pending_key, days, explanation):
    _shelf_result_queue.put((pending_key, days, explanation))


# ═══════════════════════════════════════
#  pyzbar（可选）
# ═══════════════════════════════════════
try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    import ctypes
    PYZBAR_OK = True
except ImportError:
    PYZBAR_OK = False
    print("⚠  pyzbar 未安装，条码扫描不可用。")

# ═══════════════════════════════════════
#  Pygame 初始化
# ═══════════════════════════════════════
pygame.init()
W, H = 1400, 820
screen = pygame.display.set_mode((W, H))
pygame.display.set_caption("FridgeBud v2.0")
clock = pygame.time.Clock()

# ── 字体 ──
def _load_font(size, bold=False):
    return pygame.font.SysFont("microsoftyahei,noto sans cjk sc,wenquanyi micro hei,arial", size, bold=bold)

f_xl    = _load_font(52, bold=True)
f_lg    = _load_font(28, bold=True)
f_md    = _load_font(22)
f_sm    = _load_font(18)
f_xs    = _load_font(15)

# ── Sprites ──
sprites = {}
if SPRITE_PATH.exists():
    for file in SPRITE_PATH.iterdir():
        if file.suffix == ".png":
            name = file.stem
            try:
                img = pygame.image.load(str(file)).convert_alpha()
                sprites[name] = img
            except:
                pass
    print(f"[Sprites] 已加载 {len(sprites)} 个图标")
else:
    print(f"[Sprites] 路径不存在: {SPRITE_PATH}")

def find_sprite_key(keyword):
    kw = keyword.lower()
    for sk in sprites:
        if kw in sk.lower(): return sk
    return None

LABEL_TO_SPRITE = {
    "apple":"apple","banana":"banana","carrot":"carrot","cucumber":"cucumber",
    "eggplant":"eggplant","garlic":"garlic","grapes":"grapes","kiwi":"kiwi",
    "lemon":"lemon","mango":"mango","onion":"onion","orange":"orange",
    "pear":"pear","pineapple":"pineapple","potato":"potato","strawberry":"strawberry",
    "tomato":"tomato","watermelon":"watermelon","corn":"corn","peach":"peach",
    "cherry":"cherry","ginger":"ginger","cabbage":"cabbage",
    "bell pepper":"pepper","capsicum":"pepper","chilli pepper":"pepper",
    "jalapeno":"pepper","pomegranate":"pomegranate",
}

def label_to_sprite(label):
    ll = label.lower().strip()
    if ll in LABEL_TO_SPRITE:
        k = LABEL_TO_SPRITE[ll]
        res = find_sprite_key(k)
        if res: return res
    for k, v in LABEL_TO_SPRITE.items():
        if k in ll:
            res = find_sprite_key(v)
            if res: return res
    return None

# ═══════════════════════════════════════
#  调色板 — 深色霓虹主题
# ═══════════════════════════════════════
BG          = (10,  12,  22 )
PANEL_BG    = (16,  20,  38 )
PANEL_BG2   = (22,  28,  52 )
BORDER      = (45,  55, 110 )
BORDER_LIT  = (80, 120, 255 )
NEON_CYAN   = (0,  220, 230 )
NEON_GREEN  = (50, 240, 130 )
NEON_ORANGE = (255,165,  50 )
NEON_PINK   = (255, 80, 160 )
NEON_YELLOW = (250,235,  60 )
TEXT_PRI    = (220, 230, 255 )
TEXT_SEC    = (130, 145, 190 )
TEXT_DIM    = ( 70,  80, 120 )
WHITE       = (255, 255, 255 )
BLACK       = (  0,   0,   0 )
RED_ALERT   = (255,  55,  70 )
WARN_AMB    = (255, 160,  30 )
SAFE_G      = ( 40, 200, 100 )

def glow_rect(surf, color, rect, radius=8, alpha=80, glow_size=12):
    """Draw a glowing rectangle border"""
    gl = pygame.Surface((rect.w + glow_size*2, rect.h + glow_size*2), pygame.SRCALPHA)
    for i in range(glow_size, 0, -1):
        a = int(alpha * (i/glow_size)**2)
        gr = pygame.Rect(glow_size-i, glow_size-i, rect.w+2*i, rect.h+2*i)
        pygame.draw.rect(gl, (*color, a), gr, border_radius=radius+i)
    surf.blit(gl, (rect.x - glow_size, rect.y - glow_size))

def neon_text(surf, text, font, color, pos, center=False, glow=True):
    ts = font.render(text, True, color)
    if glow:
        for offset in [(-1,-1),(1,-1),(-1,1),(1,1),(0,-2),(0,2),(-2,0),(2,0)]:
            gs = font.render(text, True, tuple(c//4 for c in color))
            r = gs.get_rect()
            if center: r.center = pos
            else: r.topleft = pos
            surf.blit(gs, (r.x+offset[0], r.y+offset[1]))
    r = ts.get_rect()
    if center: r.center = pos
    else: r.topleft = pos
    surf.blit(ts, r)
    return r

def draw_panel(surf, rect, title=None, color=NEON_CYAN, glow=True):
    """Draw a styled panel with optional title"""
    pygame.draw.rect(surf, PANEL_BG, rect, border_radius=12)
    if glow:
        glow_rect(surf, color, rect, glow_size=6, alpha=60)
    pygame.draw.rect(surf, color, rect, 1, border_radius=12)
    if title:
        th = 36
        tr = pygame.Rect(rect.x, rect.y, rect.w, th)
        title_surf = pygame.Surface((rect.w, th), pygame.SRCALPHA)
        title_surf.fill((*color, 40))
        surf.blit(title_surf, tr.topleft)
        pygame.draw.line(surf, color, (rect.x, rect.y+th), (rect.right, rect.y+th), 1)
        neon_text(surf, title, f_md, color, (rect.x+14, rect.y+8))


# ═══════════════════════════════════════
#  Physics / Animation
# ═══════════════════════════════════════
BAG_X, BAG_Y = 960, 430
BAG_W, BAG_H = 155, 180

class FlyingFruit:
    def __init__(self, sprite_key, sx, sy, tx, ty):
        self.sprite_key = sprite_key
        self.t = 0.0; self.dur = 0.38; self.done = False
        self.angle = 0.0; self.spin = random.uniform(-12, 12)
        self.p0 = (sx, sy)
        self.p1 = ((sx+tx)/2, min(sy,ty) - random.randint(70, 140))
        self.p2 = (tx, ty)
        self.trail = []
    def bezier(self, t):
        x = (1-t)**2*self.p0[0] + 2*(1-t)*t*self.p1[0] + t**2*self.p2[0]
        y = (1-t)**2*self.p0[1] + 2*(1-t)*t*self.p1[1] + t**2*self.p2[1]
        return x, y
    def update(self, dt):
        if self.done: return
        self.t = min(self.t + dt/self.dur, 1.0)
        self.angle += self.spin
        x, y = self.bezier(self.t)
        self.trail.append((x, y))
        if len(self.trail) > 10: self.trail.pop(0)
        if self.t >= 1.0: self.done = True
    def draw(self, surf):
        for i, (tx, ty) in enumerate(self.trail):
            a = int(180*(i/max(len(self.trail),1)))
            r = max(3, int(7*(i/max(len(self.trail),1))))
            s = pygame.Surface((r*2,r*2), pygame.SRCALPHA)
            pygame.draw.circle(s, (*NEON_ORANGE, a), (r,r), r)
            surf.blit(s, (int(tx)-r, int(ty)-r))
        pos = self.bezier(self.t)
        size = int(28*(0.5 + 0.5*self.t))
        if self.sprite_key in sprites:
            img = pygame.transform.scale(sprites[self.sprite_key], (size, size))
            img = pygame.transform.rotate(img, self.angle)
            surf.blit(img, img.get_rect(center=(int(pos[0]), int(pos[1]))))

class Particle:
    def __init__(self, x, y, explode=False):
        angle = random.uniform(0, math.tau) if explode else random.uniform(-math.pi, 0)
        speed = random.uniform(3, 14) if explode else random.uniform(2, 8)
        self.x = float(x); self.y = float(y)
        self.vx = math.cos(angle)*speed; self.vy = math.sin(angle)*speed
        self.life = 1.0
        self.color = random.choice([NEON_CYAN, NEON_GREEN, NEON_ORANGE,
                                    NEON_PINK, NEON_YELLOW, WHITE])
        self.r = random.randint(3, 9 if explode else 7)
    def update(self, dt):
        self.vy += 15*dt; self.x += self.vx; self.y += self.vy
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
        d = self.timer/0.35
        self.ox = math.sin(self.timer*55)*7*d
        self.oy = math.sin(self.timer*42)*3*d

def draw_bag(surf, shake, fruit_key, count):
    bx = BAG_X + shake.ox; by = BAG_Y + shake.oy
    # Neon bag glow
    bag_rect = pygame.Rect(int(bx-BAG_W//2), int(by), BAG_W, BAG_H)
    glow_rect(surf, NEON_ORANGE, bag_rect, glow_size=8, alpha=50)
    pts = [(bx-BAG_W//2+10,by),(bx+BAG_W//2-10,by),
           (bx+BAG_W//2-5,by+BAG_H),(bx-BAG_W//2+5,by+BAG_H)]
    pygame.draw.polygon(surf, (40,30,10), pts)
    pygame.draw.polygon(surf, (100,70,20), pts, 2)
    # handle
    rp = [(bx-BAG_W//2,by-12),(bx-BAG_W//2+10,by),
          (bx+BAG_W//2-10,by),(bx+BAG_W//2,by-12)]
    pygame.draw.polygon(surf, (80,60,15), rp)
    pygame.draw.polygon(surf, NEON_ORANGE, rp, 2)
    if fruit_key and fruit_key in sprites and count > 0:
        cols=4; icon_sz=20
        for i in range(min(count,12)):
            ic = pygame.transform.scale(sprites[fruit_key], (icon_sz, icon_sz))
            ix = bx-BAG_W//2+22+(i%cols)*27
            iy = by+BAG_H-28-(i//cols)*23
            surf.blit(ic, (int(ix), int(iy)))
    if count > 0:
        ct = f_md.render(f"×{count}", True, NEON_YELLOW)
        surf.blit(ct, (int(bx+BAG_W//2-18), int(by+BAG_H-32)))


# ═══════════════════════════════════════
#  UI Panels layout  (1400×820)
# ═══════════════════════════════════════
# Left  column: camera + detection       x=10..460  (450px)
# Center: PQ (fridge) + recipe           x=470..900 (430px)
# Right: analytics + shopping            x=910..1390 (480px)
# Bottom bar: queue                       y=720..810

CAM_RECT    = pygame.Rect(10,  50, 450, 338)
PQ_RECT     = pygame.Rect(470, 50, 430, 420)
REC_RECT    = pygame.Rect(470,490, 430, 220)
ANA_RECT    = pygame.Rect(910, 50, 470, 250)
SHOP_RECT   = pygame.Rect(910,315, 470, 395)
QUEUE_RECT  = pygame.Rect(10, 720, 1380, 90)

PQ_SCROLL   = 0

# ── Tab state ──
TABS        = ["冰箱", "配方", "分析", "采购"]
active_tab  = 0   # which right-panel is visible

# ═══════════════════════════════════════
#  Camera Thread
# ═══════════════════════════════════════
cv_queue = queue.Queue(maxsize=4)
cam_frame_latest = None

def camera_thread():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("无法打开摄像头"); return
    while True:
        ret, frame = cap.read()
        if ret:
            if cv_queue.qsize() >= 2: cv_queue.get()
            cv_queue.put(frame)

threading.Thread(target=camera_thread, daemon=True).start()

# ═══════════════════════════════════════
#  HuggingFace Model
# ═══════════════════════════════════════
print("加载模型...")
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
hf_model = AutoModelForImageClassification.from_pretrained(
    "jazzmacedo/fruits-and-vegetables-detector-36")
hf_model.to(device).eval()
if device.type == "cuda":
    hf_model = hf_model.half()
HF_LABELS = list(hf_model.config.id2label.values())
INFER_SIZE = 160
_normalize = transforms.Normalize(mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225])
_to_tensor  = transforms.ToTensor()

try:
    dummy = torch.zeros(1,3,INFER_SIZE,INFER_SIZE).to(device)
    if device.type == "cuda": dummy = dummy.half()
    with torch.no_grad():
        for _ in range(2): hf_model(dummy)
    print("✓ 模型预热完成")
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

# ── Barcode ──
barcode_raw_queue = queue.Queue(maxsize=2)
_bc_scan_active   = threading.Event()

def _decode_barcode(gray):
    try: return pyzbar_decode(gray)
    except: return []

def barcode_scan_thread():
    last_code = ""
    while True:
        _bc_scan_active.wait()
        if cv_queue.empty(): time.sleep(0.05); continue
        frame = list(cv_queue.queue)[-1]
        if not PYZBAR_OK: time.sleep(0.1); continue
        results = []
        for scale in (1.0, 1.5):
            if scale == 1.0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            else:
                h, w = frame.shape[:2]
                big  = cv2.resize(frame, (int(w*scale), int(h*scale)))
                gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            decoded = _decode_barcode(gray)
            if decoded: results = decoded; break
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

def lookup_barcode(code_str):
    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{code_str}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "FridgeBud/2.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        if data.get("status") == 1:
            p = data.get("product", {})
            name = (p.get("product_name_zh") or p.get("product_name_en")
                    or p.get("product_name") or "").strip()
            return name if name else None
    except: pass
    return None

barcode_result_queue = queue.Queue(maxsize=1)
barcode_lookup_busy  = False

def barcode_lookup_thread(code_str):
    global barcode_lookup_busy
    name = lookup_barcode(code_str)
    item = (code_str, name or code_str)
    if barcode_result_queue.full():
        try: barcode_result_queue.get_nowait()
        except: pass
    barcode_result_queue.put(item)
    barcode_lookup_busy = False


# ═══════════════════════════════════════
#  State Machine
# ═══════════════════════════════════════
STATE_IDLE    = "idle"
STATE_ASK     = "ask"
STATE_BAGGING = "bagging"
STATE_DONE    = "done"
STATE_BARCODE = "barcode"
STATE_RECIPE  = "recipe_edit"

state = STATE_IDLE

# ═══════════════════════════════════════
#  Helper: add to fridge PQ + DB
# ═══════════════════════════════════════
def add_to_fridge(name, sprite_key, count, barcode=""):
    pending_key = f"{name}_{time.time()}"
    _pending_shelf[pending_key] = {
        "name": name, "sprite_key": sprite_key,
        "count": count, "barcode": barcode,
        "added_date": datetime.now(),
    }
    def _cb(food_name, days, explanation):
        _shelf_result_queue.put((pending_key, days, explanation))
    threading.Thread(target=estimate_shelf_life_openai, args=(name, _cb), daemon=True).start()

def process_shelf_results():
    while not _shelf_result_queue.empty():
        try:
            pending_key, days, explanation = _shelf_result_queue.get_nowait()
        except queue.Empty:
            break
        if pending_key not in _pending_shelf: continue
        info = _pending_shelf.pop(pending_key)
        expiry = info["added_date"] + timedelta(days=days)
        item_dict = {
            "name": info["name"], "sprite_key": info["sprite_key"],
            "count": info["count"], "added_date": info["added_date"],
            "expiry_date": expiry, "shelf_days": days,
            "explanation": explanation, "barcode": info.get("barcode",""),
        }
        item_id = db.save_item(item_dict)
        item_dict["id"] = item_id
        fridge_pq.push(item_dict)
        print(f"[DB+PQ] {info['name']} ×{info['count']} 保质 {days} 天")


# ═══════════════════════════════════════
#  Recipe System
# ═══════════════════════════════════════
recipes_cache = db.load_recipes()

def compute_servings(recipe):
    """计算冰箱里能做几份这道菜"""
    items = fridge_pq.all_items()
    stock = {}
    for it in items:
        key = it["name"].lower()
        stock[key] = stock.get(key, 0) + it["count"]
    if not recipe["ingredients"]:
        return 0
    mins = []
    for ing in recipe["ingredients"]:
        iname = ing["ingredient"].lower()
        need  = ing["amount"]
        have  = 0
        for k in stock:
            if iname in k or k in iname:
                have += stock[k]
                break
        if need > 0:
            mins.append(int(have / need))
        else:
            mins.append(999)
    return min(mins) if mins else 0

def compute_shopping_plan(recipe, target_servings=4):
    """生成采购清单"""
    items = fridge_pq.all_items()
    stock = {}
    for it in items:
        key = it["name"].lower()
        stock[key] = stock.get(key, 0) + it["count"]
    plan = []
    for ing in recipe["ingredients"]:
        iname = ing["ingredient"].lower()
        need  = ing["amount"] * target_servings
        have  = 0
        for k in stock:
            if iname in k or k in iname:
                have += stock[k]
                break
        shortage = need - have
        if shortage > 0:
            plan.append({
                "ingredient": ing["ingredient"],
                "need": need,
                "have": have,
                "buy": shortage,
                "unit": ing.get("unit","pcs")
            })
    return plan


# ═══════════════════════════════════════
#  Dialog classes
# ═══════════════════════════════════════
class NeonButton:
    def __init__(self, rect, text, color=NEON_CYAN):
        self.rect    = pygame.Rect(rect)
        self.text    = text
        self.color   = color
        self.clicked = False
        self._pulse  = 0.0
        self.hovered = False

    def update(self, dt, mp):
        self.hovered = self.rect.collidepoint(mp)
        self._pulse += dt * 3

    def draw(self, surf):
        scale = 1.0 + 0.03*math.sin(self._pulse) if self.hovered else 1.0
        w, h = int(self.rect.w*scale), int(self.rect.h*scale)
        r = pygame.Rect(self.rect.centerx-w//2, self.rect.centery-h//2, w, h)
        col = tuple(min(255, c+40) for c in self.color) if self.hovered else self.color
        # fill
        fill_s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        fill_s.fill((*self.color, 35))
        surf.blit(fill_s, r.topleft)
        glow_rect(surf, col, r, glow_size=5, alpha=60)
        pygame.draw.rect(surf, col, r, 1, border_radius=8)
        neon_text(surf, self.text, f_md, col, r.center, center=True, glow=True)

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and self.rect.collidepoint(event.pos):
            self.clicked = True

class AskDialog:
    def __init__(self, label, sprite_key, conf):
        self.label = label; self.sprite_key = sprite_key; self.conf = conf
        cx, cy = W//2, H//2
        self.btn_one  = NeonButton((cx-170, cy+60, 150, 52), "1 个", NEON_GREEN)
        self.btn_many = NeonButton((cx+20,  cy+60, 150, 52), "多 个", NEON_ORANGE)
        self.btn_skip = NeonButton((cx-65,  cy+130, 130, 40),"✕ 跳过", NEON_PINK)
        self.choice   = None

    def update(self, dt, mp):
        for b in [self.btn_one, self.btn_many, self.btn_skip]: b.update(dt, mp)

    def draw(self, surf, mp):
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        surf.blit(ov, (0, 0))
        cx, cy = W//2, H//2
        box = pygame.Rect(cx-220, cy-120, 440, 290)
        draw_panel(surf, box, color=NEON_CYAN)
        if self.sprite_key in sprites:
            icon = pygame.transform.scale(sprites[self.sprite_key], (60, 60))
            surf.blit(icon, (box.centerx-30, box.y+40))
        neon_text(surf, self.label.replace("_"," ").title(), f_lg,
                  NEON_YELLOW, (box.centerx, box.y+110), center=True)
        neon_text(surf, f"置信度 {self.conf:.0%}", f_sm, TEXT_SEC,
                  (box.centerx, box.y+142), center=True, glow=False)
        neon_text(surf, "加几个？", f_md, TEXT_PRI,
                  (box.centerx, box.y+166), center=True, glow=False)
        for b in [self.btn_one, self.btn_many, self.btn_skip]: b.draw(surf)

    def handle(self, event):
        self.btn_one.handle(event)
        self.btn_many.handle(event)
        self.btn_skip.handle(event)
        if self.btn_one.clicked:  self.choice = 1
        if self.btn_many.clicked: self.choice = "many"
        if self.btn_skip.clicked: self.choice = "skip"

class BarcodeDialog:
    def __init__(self, code, name):
        self.code = code; self.name = name; self.count = 1; self.choice = None
        cx, cy = W//2, H//2
        self.btn_add   = NeonButton((cx-80, cy+90, 160, 52),  "加入冰箱", NEON_GREEN)
        self.btn_skip  = NeonButton((cx-80, cy+155, 160, 48), "✕ 跳过",   NEON_PINK)
        self.btn_plus  = NeonButton((cx+50, cy+20,  44, 44),  "+", NEON_ORANGE)
        self.btn_minus = NeonButton((cx-90, cy+20,  44, 44),  "−", NEON_CYAN)

    def update(self, dt, mp):
        for b in [self.btn_add, self.btn_skip, self.btn_plus, self.btn_minus]:
            b.update(dt, mp)

    def draw(self, surf, mp):
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        surf.blit(ov, (0, 0))
        cx, cy = W//2, H//2
        box = pygame.Rect(cx-220, cy-130, 440, 320)
        draw_panel(surf, box, "条码商品", color=NEON_CYAN)
        disp = self.name if len(self.name) <= 22 else self.name[:20]+"…"
        neon_text(surf, disp, f_lg, NEON_YELLOW, (box.centerx, box.y+56), center=True)
        neon_text(surf, f"条码: {self.code}", f_xs, TEXT_SEC,
                  (box.centerx, box.y+90), center=True, glow=False)
        neon_text(surf, "数量:", f_md, TEXT_PRI, (cx-90, cy+27), glow=False)
        cnt_s = f_xl.render(str(self.count), True, NEON_ORANGE)
        surf.blit(cnt_s, cnt_s.get_rect(center=(cx, cy+40)))
        for b in [self.btn_add, self.btn_skip, self.btn_plus, self.btn_minus]: b.draw(surf)

    def handle(self, event):
        for b in [self.btn_add, self.btn_skip, self.btn_plus, self.btn_minus]:
            b.handle(event)
        if self.btn_add.clicked:   self.choice = "add"
        if self.btn_skip.clicked:  self.choice = "skip"
        if self.btn_plus.clicked:  self.count = min(99, self.count+1); self.btn_plus.clicked=False
        if self.btn_minus.clicked: self.count = max(1,  self.count-1); self.btn_minus.clicked=False


class RecipeEditDialog:
    """新建/编辑配方对话框"""
    def __init__(self, existing=None):
        self.existing = existing
        self.name     = existing["name"]       if existing else ""
        self.servings = existing["servings"]   if existing else 1
        self.desc     = existing["description"] or "" if existing else ""
        # ingredients: list of {"ingredient":str, "amount":float, "unit":str}
        self.ings = list(existing["ingredients"]) if existing else []
        self.ing_input  = ""
        self.amt_input  = "1"
        self.unit_input = "pcs"
        self.active_field = None   # "name","ing","amt","unit","desc"
        self.choice  = None
        self.msg     = ""
        self.scroll  = 0

        bx, by = W//2, H//2
        self.field_rects = {
            "name": pygame.Rect(bx-180, by-195, 360, 36),
            "desc": pygame.Rect(bx-180, by-140, 360, 36),
            "ing":  pygame.Rect(bx-180, by-20,  180, 34),
            "amt":  pygame.Rect(bx+10,  by-20,  80,  34),
            "unit": pygame.Rect(bx+100, by-20,  82,  34),
        }
        self.btn_add_ing  = NeonButton((bx-180, by+24,  120, 34), "+ 添加", NEON_CYAN)
        self.btn_save     = NeonButton((bx-100, by+200, 200, 50), "保存配方", NEON_GREEN)
        self.btn_cancel   = NeonButton((bx+110, by+200, 100, 50), "取消",    NEON_PINK)

    def update(self, dt, mp):
        self.btn_add_ing.update(dt, mp)
        self.btn_save.update(dt, mp)
        self.btn_cancel.update(dt, mp)

    def draw(self, surf, mp):
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0,0,0,170)); surf.blit(ov,(0,0))
        bx, by = W//2, H//2
        box = pygame.Rect(bx-220, by-240, 440, 510)
        draw_panel(surf, box, "新建配方" if not self.existing else "编辑配方",
                   color=NEON_PINK)

        # Fields
        labels = {"name":"菜名", "desc":"描述", "ing":"食材", "amt":"用量", "unit":"单位"}
        values = {"name": self.name, "desc": self.desc,
                  "ing":  self.ing_input, "amt": self.amt_input, "unit": self.unit_input}
        for key, rect in self.field_rects.items():
            active = self.active_field == key
            col = NEON_CYAN if active else BORDER
            pygame.draw.rect(surf, PANEL_BG2, rect, border_radius=6)
            pygame.draw.rect(surf, col, rect, 1, border_radius=6)
            neon_text(surf, labels[key], f_xs, TEXT_SEC,
                      (rect.x, rect.y-16), glow=False)
            val = values[key]
            if active and (time.time() % 1.0) < 0.5: val += "|"
            neon_text(surf, val, f_sm, TEXT_PRI, (rect.x+8, rect.y+8), glow=False)

        # Ingredients list
        neon_text(surf, "配料列表:", f_sm, TEXT_PRI, (bx-180, by+68), glow=False)
        clip_rect = pygame.Rect(bx-180, by+88, 360, 90)
        surf.set_clip(clip_rect)
        for i, ing in enumerate(self.ings[self.scroll:self.scroll+3]):
            iy = by+88 + i*30
            pygame.draw.rect(surf, PANEL_BG2, pygame.Rect(bx-180, iy, 320, 26), border_radius=4)
            pygame.draw.rect(surf, BORDER,    pygame.Rect(bx-180, iy, 320, 26), 1, border_radius=4)
            txt = f"{ing['ingredient']}  {ing['amount']} {ing['unit']}"
            neon_text(surf, txt, f_xs, TEXT_PRI, (bx-172, iy+6), glow=False)
            # delete
            dx = pygame.Rect(bx+142, iy+2, 22, 22)
            pygame.draw.rect(surf, (60,20,20), dx, border_radius=4)
            neon_text(surf, "✕", f_xs, NEON_PINK, dx.center, center=True, glow=False)
        surf.set_clip(None)

        self.btn_add_ing.draw(surf)
        self.btn_save.draw(surf)
        self.btn_cancel.draw(surf)
        if self.msg:
            neon_text(surf, self.msg, f_xs, NEON_ORANGE,
                      (bx, by+165), center=True, glow=False)

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            pos = event.pos
            for key, rect in self.field_rects.items():
                if rect.collidepoint(pos):
                    self.active_field = key; return
            self.active_field = None
            bx, by = W//2, H//2
            # Delete ingredient buttons
            for i, ing in enumerate(self.ings[self.scroll:self.scroll+3]):
                iy = by+88 + i*30
                dx = pygame.Rect(bx+142, iy+2, 22, 22)
                if dx.collidepoint(pos):
                    self.ings.pop(self.scroll+i); return
            self.btn_add_ing.handle(event)
            self.btn_save.handle(event)
            self.btn_cancel.handle(event)
            if self.btn_add_ing.clicked:
                self.btn_add_ing.clicked = False
                if self.ing_input.strip():
                    try: amt = float(self.amt_input)
                    except: amt = 1.0
                    self.ings.append({
                        "ingredient": self.ing_input.strip(),
                        "amount": amt,
                        "unit": self.unit_input.strip() or "pcs"
                    })
                    self.ing_input = ""; self.amt_input = "1"
                    self.msg = f"已添加: {self.ings[-1]['ingredient']}"
                else:
                    self.msg = "请输入食材名称"
            if self.btn_save.clicked:
                self.btn_save.clicked = False
                if not self.name.strip():
                    self.msg = "请输入菜名"
                elif not self.ings:
                    self.msg = "请至少添加一种食材"
                else:
                    self.choice = "save"
            if self.btn_cancel.clicked:
                self.choice = "cancel"

        if event.type == pygame.KEYDOWN and self.active_field:
            field_map = {
                "name": "name", "desc": "desc",
                "ing":  "ing_input", "amt": "amt_input", "unit": "unit_input"
            }
            attr = field_map[self.active_field]
            cur  = getattr(self, attr)
            if event.key == pygame.K_BACKSPACE:
                setattr(self, attr, cur[:-1])
            elif event.key == pygame.K_TAB:
                keys = list(self.field_rects.keys())
                idx  = keys.index(self.active_field)
                self.active_field = keys[(idx+1) % len(keys)]
            elif event.key == pygame.K_RETURN:
                self.active_field = None
            elif event.unicode and len(cur) < 60:
                setattr(self, attr, cur + event.unicode)


# ═══════════════════════════════════════
#  Draw PQ panel (fridge inventory)
# ═══════════════════════════════════════
def draw_pq_panel(surf, pq, mp):
    global PQ_SCROLL
    rect = PQ_RECT
    draw_panel(surf, rect, f"🧊 冰箱 ({FRIDGE_TEMP_C}°C)  [{len(pq)} 项]",
               color=NEON_CYAN)

    items = pq.all_items()
    if not items:
        neon_text(surf, "空 — 添加食物后自动排序", f_sm, TEXT_DIM,
                  (rect.centerx, rect.centery), center=True, glow=False)
        return

    now = datetime.now()
    row_h = 52
    visible = (rect.h - 46) // row_h
    max_scroll = max(0, len(items)-visible)
    PQ_SCROLL  = min(PQ_SCROLL, max_scroll)

    clip = pygame.Rect(rect.x+4, rect.y+40, rect.w-8, rect.h-44)
    surf.set_clip(clip)

    for idx, item in enumerate(items):
        if idx < PQ_SCROLL: continue
        vi = idx - PQ_SCROLL
        if vi >= visible+1: break
        ry = rect.y+42 + vi*row_h
        rr = pygame.Rect(rect.x+6, ry, rect.w-12, row_h-4)

        days_left = (item["expiry_date"] - now).days
        if days_left < 0:
            col = RED_ALERT; bg = (50,10,10); status = f"已过期 {-days_left}天!"
        elif days_left <= 2:
            col = NEON_ORANGE; bg = (45,25,10); status = f"⚠ 剩 {days_left} 天!"
        elif days_left <= 5:
            col = NEON_YELLOW; bg = (40,38,10); status = f"剩 {days_left} 天"
        else:
            col = NEON_GREEN; bg = (10,38,20); status = f"剩 {days_left} 天"

        pygame.draw.rect(surf, bg, rr, border_radius=7)
        pygame.draw.rect(surf, col, rr, 1, border_radius=7)

        # rank
        neon_text(surf, f"#{idx+1}", f_xs, TEXT_DIM, (rr.x+5, rr.y+16), glow=False)

        # icon
        sk = item.get("sprite_key")
        if sk and sk in sprites:
            icon = pygame.transform.scale(sprites[sk], (30, 30))
            surf.blit(icon, (rr.x+36, rr.y+9))

        # name
        disp = item["name"].replace("_"," ").title()
        if len(disp) > 11: disp = disp[:10]+"…"
        neon_text(surf, f"{disp} ×{item['count']}", f_sm, TEXT_PRI,
                  (rr.x+72, rr.y+6), glow=False)
        neon_text(surf, item["expiry_date"].strftime("到期 %m/%d"), f_xs, TEXT_SEC,
                  (rr.x+72, rr.y+28), glow=False)
        neon_text(surf, status, f_xs, col, (rr.right-90, rr.y+14), glow=False)

        # Remove button on hover
        if rr.collidepoint(mp):
            del_btn = pygame.Rect(rr.right-28, rr.y+10, 22, 22)
            pygame.draw.rect(surf, (60,10,10), del_btn, border_radius=4)
            neon_text(surf, "✕", f_xs, NEON_PINK, del_btn.center, center=True, glow=False)
            if item.get("explanation"):
                _draw_tooltip(surf, mp[0], mp[1], item["explanation"])

    surf.set_clip(None)
    if len(items) > visible:
        if PQ_SCROLL > 0:
            neon_text(surf, "▲", f_xs, NEON_CYAN, (rect.right-24, rect.y+42), glow=False)
        if PQ_SCROLL < max_scroll:
            neon_text(surf, "▼", f_xs, NEON_CYAN, (rect.right-24, rect.bottom-18), glow=False)


def _draw_tooltip(surf, mx, my, text):
    max_w = 250
    words = text.split()
    lines = []; line = ""
    for w in words:
        test = (line+" "+w).strip()
        if f_xs.size(test)[0] > max_w:
            if line: lines.append(line)
            line = w
        else: line = test
    if line: lines.append(line)
    lh = 15
    tw = max(f_xs.size(l)[0] for l in lines)+16
    th = len(lines)*lh+12
    tx = min(mx+14, W-tw-4); ty = max(my-th-6, 4)
    ts = pygame.Surface((tw, th), pygame.SRCALPHA)
    ts.fill((10, 15, 40, 230))
    pygame.draw.rect(ts, NEON_CYAN, (0,0,tw,th), 1, border_radius=6)
    for i, l in enumerate(lines):
        ls = f_xs.render(l, True, TEXT_PRI)
        ts.blit(ls, (8, 6+i*lh))
    surf.blit(ts, (tx, ty))


# ═══════════════════════════════════════
#  Draw Recipe Panel
# ═══════════════════════════════════════
rec_scroll = 0

def draw_recipe_panel(surf, mp):
    global rec_scroll
    rect = REC_RECT
    draw_panel(surf, rect, f"📋 配方 ({len(recipes_cache)} 个)", color=NEON_PINK)

    if not recipes_cache:
        neon_text(surf, "暂无配方 — 右键菜单新建", f_sm, TEXT_DIM,
                  (rect.centerx, rect.centery), center=True, glow=False)
        return

    row_h = 50
    visible = (rect.h - 46) // row_h
    max_scroll = max(0, len(recipes_cache)-visible)
    rec_scroll = min(rec_scroll, max_scroll)

    clip = pygame.Rect(rect.x+4, rect.y+40, rect.w-8, rect.h-44)
    surf.set_clip(clip)

    for idx, rec in enumerate(recipes_cache):
        if idx < rec_scroll: continue
        vi = idx - rec_scroll
        if vi >= visible+1: break
        ry = rect.y+42 + vi*row_h
        rr = pygame.Rect(rect.x+6, ry, rect.w-12, row_h-4)
        hov = rr.collidepoint(mp)
        bg  = (28,18,48) if hov else (18,12,35)
        pygame.draw.rect(surf, bg, rr, border_radius=7)
        pygame.draw.rect(surf, NEON_PINK if hov else BORDER, rr, 1, border_radius=7)

        servings = compute_servings(rec)
        col_s = NEON_GREEN if servings > 0 else RED_ALERT
        neon_text(surf, rec["name"][:16], f_sm, TEXT_PRI, (rr.x+10, rr.y+6), glow=False)
        neon_text(surf, f"可做 {servings} 份", f_xs, col_s, (rr.x+10, rr.y+26), glow=False)
        ings_str = " · ".join(i["ingredient"] for i in rec["ingredients"][:3])
        if len(rec["ingredients"]) > 3: ings_str += "…"
        neon_text(surf, ings_str, f_xs, TEXT_SEC, (rr.right-200, rr.y+16), glow=False)

    surf.set_clip(None)


# ═══════════════════════════════════════
#  Draw Analytics panel
# ═══════════════════════════════════════
def draw_analytics_panel(surf, mp):
    rect = ANA_RECT
    draw_panel(surf, rect, "📊 分析 & 预测", color=NEON_YELLOW)

    expiry_soon = db.get_expiry_soon(within_days=3)
    y = rect.y+44
    if expiry_soon:
        neon_text(surf, "即将过期 (≤3天):", f_sm, NEON_ORANGE, (rect.x+14, y), glow=False)
        y += 22
        for item in expiry_soon[:4]:
            exp = datetime.fromisoformat(item["earliest"])
            days_left = (exp - datetime.now()).days
            col = RED_ALERT if days_left < 0 else WARN_AMB
            txt = f"• {item['name']}  ×{item['total']}  ({days_left}天)"
            neon_text(surf, txt, f_xs, col, (rect.x+18, y), glow=False)
            y += 18
    else:
        neon_text(surf, "✓ 暂无即将过期食材", f_sm, NEON_GREEN, (rect.x+14, y), glow=False)
        y += 26

    y += 6
    neon_text(surf, f"冰箱总品类: {len(set(i['name'] for i in fridge_pq.all_items()))}", f_sm,
              TEXT_PRI, (rect.x+14, y), glow=False); y += 22
    total_items = sum(i['count'] for i in fridge_pq.all_items())
    neon_text(surf, f"冰箱总数量: {total_items}", f_sm, TEXT_PRI, (rect.x+14, y), glow=False)


# ═══════════════════════════════════════
#  Draw Shopping Plan panel
# ═══════════════════════════════════════
shop_rec_idx  = 0
shop_target   = 4
shop_scroll   = 0

def draw_shopping_panel(surf, mp):
    global shop_rec_idx, shop_target
    rect = SHOP_RECT
    draw_panel(surf, rect, "🛒 采购方案", color=NEON_ORANGE)

    if not recipes_cache:
        neon_text(surf, "暂无配方，先添加配方", f_sm, TEXT_DIM,
                  (rect.centerx, rect.centery), center=True, glow=False)
        return

    shop_rec_idx = min(shop_rec_idx, len(recipes_cache)-1)
    rec = recipes_cache[shop_rec_idx]

    # Recipe selector
    prev_btn = pygame.Rect(rect.x+8,  rect.y+44, 30, 26)
    next_btn = pygame.Rect(rect.right-38, rect.y+44, 30, 26)
    pygame.draw.rect(surf, PANEL_BG2, prev_btn, border_radius=4)
    pygame.draw.rect(surf, BORDER, prev_btn, 1, border_radius=4)
    pygame.draw.rect(surf, PANEL_BG2, next_btn, border_radius=4)
    pygame.draw.rect(surf, BORDER, next_btn, 1, border_radius=4)
    neon_text(surf, "◀", f_xs, TEXT_PRI, prev_btn.center, center=True, glow=False)
    neon_text(surf, "▶", f_xs, TEXT_PRI, next_btn.center, center=True, glow=False)

    disp_name = rec["name"][:20]
    neon_text(surf, disp_name, f_md, NEON_ORANGE, (rect.centerx, rect.y+57), center=True)

    # Target servings
    ts_label = pygame.Rect(rect.x+10, rect.y+82, 260, 22)
    neon_text(surf, f"目标份数: {shop_target}  (滚轮调整)", f_xs, TEXT_SEC,
              ts_label.topleft, glow=False)
    can_make = compute_servings(rec)
    col_s = NEON_GREEN if can_make >= shop_target else WARN_AMB
    neon_text(surf, f"当前可做: {can_make} 份", f_sm, col_s,
              (rect.x+260, rect.y+80), glow=False)

    plan = compute_shopping_plan(rec, shop_target)
    y = rect.y+108
    if not plan:
        neon_text(surf, "✓ 食材充足，无需采购！", f_md, NEON_GREEN,
                  (rect.centerx, y+20), center=True)
    else:
        # Header
        pygame.draw.line(surf, BORDER, (rect.x+8, y), (rect.right-8, y))
        y += 6
        neon_text(surf, "食材", f_xs, TEXT_DIM, (rect.x+12, y), glow=False)
        neon_text(surf, "现有", f_xs, TEXT_DIM, (rect.x+190, y), glow=False)
        neon_text(surf, "需要", f_xs, TEXT_DIM, (rect.x+245, y), glow=False)
        neon_text(surf, "购买", f_xs, TEXT_DIM, (rect.x+300, y), glow=False)
        y += 18
        pygame.draw.line(surf, BORDER, (rect.x+8, y), (rect.right-8, y))
        y += 4
        clip = pygame.Rect(rect.x+4, y, rect.w-8, rect.h-(y-rect.y)-10)
        surf.set_clip(clip)
        for item in plan:
            if y > rect.bottom-18: break
            row = pygame.Rect(rect.x+6, y, rect.w-12, 22)
            pygame.draw.rect(surf, (25,20,10), row, border_radius=4)
            neon_text(surf, item["ingredient"][:14], f_xs, TEXT_PRI, (rect.x+12, y+4), glow=False)
            neon_text(surf, f"{item['have']:.0f}", f_xs, TEXT_SEC, (rect.x+192, y+4), glow=False)
            neon_text(surf, f"{item['need']:.0f}", f_xs, TEXT_SEC, (rect.x+247, y+4), glow=False)
            buy_s = f"+{item['buy']:.0f} {item['unit']}"
            neon_text(surf, buy_s, f_xs, NEON_ORANGE, (rect.x+300, y+4), glow=False)
            y += 26
        surf.set_clip(None)

    return prev_btn, next_btn


# ═══════════════════════════════════════
#  Draw Camera Panel
# ═══════════════════════════════════════
MODE_BTN = pygame.Rect(W-215, 8, 200, 38)

def draw_camera_panel(surf, frame_bgr, last_label, last_conf):
    rect = CAM_RECT
    draw_panel(surf, rect, None, color=NEON_CYAN, glow=True)

    if frame_bgr is not None:
        try:
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            cam_surf = pygame.surfarray.make_surface(np.transpose(rgb, (1, 0, 2)))
            cam_surf = pygame.transform.scale(cam_surf, (rect.w-4, rect.h-4))
            surf.blit(cam_surf, (rect.x+2, rect.y+2))
        except Exception:
            pass
    else:
        neon_text(surf, "无摄像头信号", f_md, TEXT_DIM,
                  (rect.centerx, rect.centery), center=True, glow=False)

    pygame.draw.rect(surf, NEON_CYAN, rect, 1, border_radius=12)

    if last_label:
        col = NEON_GREEN if last_conf > 0.75 else NEON_YELLOW
        ts  = f_sm.render(f"识别: {last_label}  ({last_conf:.0%})", True, col)
        bg  = pygame.Surface((ts.get_width()+16, ts.get_height()+8), pygame.SRCALPHA)
        bg.fill((0,0,0,160))
        surf.blit(bg, (rect.x+8, rect.bottom-ts.get_height()-14))
        surf.blit(ts, (rect.x+16, rect.bottom-ts.get_height()-10))


def draw_mode_btn(surf, mp):
    is_bc = state == STATE_BARCODE
    col   = NEON_CYAN if is_bc else NEON_PINK
    hov   = MODE_BTN.collidepoint(mp)
    fill_s = pygame.Surface((MODE_BTN.w, MODE_BTN.h), pygame.SRCALPHA)
    fill_s.fill((*col, 30 if hov else 15))
    surf.blit(fill_s, MODE_BTN.topleft)
    glow_rect(surf, col, MODE_BTN, glow_size=4, alpha=50)
    pygame.draw.rect(surf, col, MODE_BTN, 1, border_radius=8)
    label = "📸 摄像头识别" if is_bc else "🔲 扫条码"
    neon_text(surf, label, f_sm, col, MODE_BTN.center, center=True)


# ── OKButton ──
class OKButton:
    def __init__(self):
        self.rect = pygame.Rect(1160, 640, 200, 70)
        self.hovered = False; self.clicked = False; self._p = 0.0
    def update(self, dt, mp):
        self.hovered = self.rect.collidepoint(mp); self._p += dt*3
    def draw(self, surf):
        col  = NEON_GREEN
        scale = 1.0 + 0.04*math.sin(self._p)
        w, h = int(self.rect.w*scale), int(self.rect.h*scale)
        r = pygame.Rect(self.rect.centerx-w//2, self.rect.centery-h//2, w, h)
        fill_s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        fill_s.fill((*col, 40))
        surf.blit(fill_s, r.topleft)
        glow_rect(surf, col, r, glow_size=6, alpha=80)
        pygame.draw.rect(surf, col, r, 2, border_radius=12)
        neon_text(surf, "✓  OK", f_lg, col, r.center, center=True)
    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and self.rect.collidepoint(event.pos):
            self.clicked = True

# ── New Recipe Button ──
new_rec_btn = NeonButton((REC_RECT.right-110, REC_RECT.y+6, 100, 28), "+ 新配方", NEON_PINK)

# ═══════════════════════════════════════
#  Bottom queue bar
# ═══════════════════════════════════════
shopping_queue = []

def draw_queue_bar(surf, mp):
    rect = QUEUE_RECT
    draw_panel(surf, rect, None, color=BORDER, glow=False)
    neon_text(surf, "本次入库:", f_sm, TEXT_SEC, (rect.x+12, rect.y+28), glow=False)
    if shopping_queue:
        ix = rect.x+105
        for entry in shopping_queue:
            sk  = entry[0]; cnt = entry[1]
            lbl = entry[2] if len(entry)>2 else ""
            if sk and sk in sprites:
                icon = pygame.transform.scale(sprites[sk], (40, 40))
                surf.blit(icon, (ix, rect.y+22))
            ct = f_sm.render(f"×{cnt}", True, NEON_ORANGE)
            surf.blit(ct, (ix+42, rect.y+32))
            if lbl and lbl != sk:
                short = lbl[:10]+"…" if len(lbl)>10 else lbl
                ls = f_xs.render(short, True, TEXT_SEC)
                surf.blit(ls, (ix, rect.y+10))
            ix += 110
    else:
        neon_text(surf, "—", f_sm, TEXT_DIM, (rect.x+115, rect.y+28), glow=False)


# ═══════════════════════════════════════
#  Title bar
# ═══════════════════════════════════════
def draw_titlebar(surf):
    # Gradient-ish bar
    for i in range(45):
        alpha = int(255*(1 - i/44)*0.9)
        pygame.draw.line(surf, (10, 12+i//2, 30+i//2), (0, i), (W, i))
    neon_text(surf, "❄ FridgeBud v2.0", f_lg, NEON_CYAN, (14, 8))
    now = datetime.now()
    neon_text(surf, now.strftime("%Y-%m-%d  %H:%M"), f_sm, TEXT_SEC,
              (580, 12), glow=False)
    if _pending_shelf:
        neon_text(surf, f"⏳ 估算中 ({len(_pending_shelf)})", f_xs, NEON_YELLOW,
                  (820, 18), glow=False)
    expiring_count = len(db.get_expiry_soon(within_days=2))
    if expiring_count:
        neon_text(surf, f"⚠ {expiring_count} 项即将过期!", f_xs, RED_ALERT,
                  (420, 18), glow=False)


# ═══════════════════════════════════════
#  Main loop variables
# ═══════════════════════════════════════
ok_button   = OKButton()
bag_shake   = BagShake()
flying      = []
particles   = []
done_parts  = []
ask_dialog      = None
barcode_dialog  = None
recipe_dialog   = None
barcode_last_scan    = ""
barcode_cooldown     = 0.0
barcode_overlay_rects= []
barcode_lookup_busy  = False
cur_label   = ""; cur_sprite = None; cur_conf = 0.0
last_label_disp = ""; last_conf_disp = 0.0
bag_count   = 0; bag_sprite  = None
detect_cooldown = 0.0
click_pending = 0; click_timer = 0.0
CLICK_INTERVAL = 0.18
shop_prev_btn = None; shop_next_btn = None

# ─── star background ───
STARS = [(random.randint(0,W), random.randint(0,H),
          random.uniform(0.3,1.0), random.uniform(0,math.tau))
         for _ in range(120)]

def draw_bg(surf, t):
    surf.fill(BG)
    for sx, sy, brightness, phase in STARS:
        twinkle = 0.6 + 0.4*math.sin(t*1.5 + phase)
        a = int(brightness * twinkle * 180)
        r = 1 if brightness < 0.6 else 2
        s = pygame.Surface((r*2,r*2), pygame.SRCALPHA)
        pygame.draw.circle(s, (180,200,255,a), (r,r), r)
        surf.blit(s, (sx-r, sy-r))

running = True
t = 0.0

# ═══════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════
while running:
    dt = clock.tick(60) / 1000.0
    t += dt
    mp = pygame.mouse.get_pos()

    # ── Update shelf results ──
    process_shelf_results()

    # ── Camera frame ──
    if not cv_queue.empty():
        cam_frame_latest = list(cv_queue.queue)[-1]

    # ── Detection ──
    detect_cooldown = max(0, detect_cooldown - dt)
    if state == STATE_IDLE and detect_cooldown <= 0:
        if not detect_queue.empty():
            try:
                lbl, conf = detect_queue.get_nowait()
                last_label_disp = lbl; last_conf_disp = conf
                skey = label_to_sprite(lbl)
                if skey:
                    cur_label = lbl; cur_sprite = skey; cur_conf = conf
                    state = STATE_ASK
                    ask_dialog = AskDialog(lbl, skey, conf)
                    detect_cooldown = 1.5
            except queue.Empty:
                pass

    # ── Barcode ──
    barcode_cooldown = max(0, barcode_cooldown - dt)
    if state == STATE_BARCODE and barcode_cooldown <= 0 and not barcode_dialog:
        if not barcode_raw_queue.empty():
            try:
                code, rects = barcode_raw_queue.get_nowait()
                barcode_overlay_rects = rects
                if code != barcode_last_scan and not barcode_lookup_busy:
                    barcode_last_scan = code; barcode_lookup_busy = True
                    threading.Thread(target=barcode_lookup_thread, args=(code,), daemon=True).start()
            except queue.Empty: pass
        if not barcode_result_queue.empty() and not barcode_dialog:
            try:
                code_str, name = barcode_result_queue.get_nowait()
                barcode_dialog = BarcodeDialog(code_str, name)
            except queue.Empty: pass

    # ── Animations ──
    for fo in flying:
        fo.update(dt)
    flying = [fo for fo in flying if not fo.done]
    if any(fo.done for fo in flying):
        bag_shake.trigger()
    for p in particles:  p.update(dt)
    particles = [p for p in particles if p.life > 0]
    for p in done_parts: p.update(dt)
    done_parts = [p for p in done_parts if p.life > 0]
    bag_shake.update(dt)

    if click_timer > 0:
        click_timer -= dt
        if click_timer <= 0 and click_pending > 0:
            n = click_pending; click_pending = 0
            for _ in range(n):
                flying.append(FlyingFruit(cur_sprite,
                    CAM_RECT.centerx+random.randint(-20,20),
                    CAM_RECT.centery+random.randint(-25,25),
                    BAG_X, BAG_Y+8))
                bag_count += 1
                for _ in range(5):
                    particles.append(Particle(BAG_X, BAG_Y+BAG_H//2))

    ok_button.update(dt, mp)
    new_rec_btn.update(dt, mp)
    if ask_dialog:     ask_dialog.update(dt, mp)
    if barcode_dialog: barcode_dialog.update(dt, mp)
    if recipe_dialog:  recipe_dialog.update(dt, mp)

    # ══════ DRAW ══════
    draw_bg(screen, t)
    draw_titlebar(screen)

    # Camera panel
    draw_camera_panel(screen, cam_frame_latest, last_label_disp, last_conf_disp)

    # IDLE hint
    if state == STATE_IDLE:
        hint = f_sm.render("把食物对准摄像头...", True, TEXT_DIM)
        screen.blit(hint, (CAM_RECT.x+10, CAM_RECT.bottom+10))

    # PQ panel
    draw_pq_panel(screen, fridge_pq, mp)

    # Recipe panel
    draw_recipe_panel(screen, mp)
    new_rec_btn.draw(screen)

    # Analytics panel
    draw_analytics_panel(screen, mp)

    # Shopping panel
    result = draw_shopping_panel(screen, mp)
    if result:
        shop_prev_btn, shop_next_btn = result

    # Barcode overlay
    if state == STATE_BARCODE and cam_frame_latest is not None:
        for (bx, by, bw, bh) in barcode_overlay_rects:
            sx = int(bx * CAM_RECT.w / cam_frame_latest.shape[1]) + CAM_RECT.x
            sy = int(by * CAM_RECT.h / cam_frame_latest.shape[0]) + CAM_RECT.y
            sw = int(bw * CAM_RECT.w / cam_frame_latest.shape[1])
            sh = int(bh * CAM_RECT.h / cam_frame_latest.shape[0])
            pygame.draw.rect(screen, NEON_GREEN, (sx, sy, sw, sh), 2)
            glow_rect(screen, NEON_GREEN, pygame.Rect(sx,sy,sw,sh), glow_size=4, alpha=60)

    # Mode button
    draw_mode_btn(screen, mp)

    # Bag
    if state in (STATE_BAGGING, STATE_DONE) or bag_count > 0:
        neon_text(screen, "购物袋", f_sm, NEON_ORANGE, (BAG_X-38, BAG_Y-30))
        draw_bag(screen, bag_shake, bag_sprite, bag_count)

    # Bagging pulse border
    if state == STATE_BAGGING:
        brect = pygame.Rect(BAG_X-BAG_W//2-14, BAG_Y-26, BAG_W+28, BAG_H+40)
        pw = int(2 + 2*math.sin(t*8))
        glow_rect(screen, NEON_ORANGE, brect, glow_size=8, alpha=60)
        pygame.draw.rect(screen, NEON_ORANGE, brect, pw, border_radius=8)
        arr_y = int(BAG_Y-50 + 5*math.sin(t*5))
        neon_text(screen, "▼ 点击添加", f_md, NEON_ORANGE,
                  (BAG_X, arr_y), center=True)

    # Animations
    for fo in flying:   fo.draw(screen)
    for p in particles: p.draw(screen)

    # Queue bar
    draw_queue_bar(screen, mp)

    # OK button
    if bag_count > 0 and state != STATE_DONE:
        ok_button.draw(screen)

    # ASK dialog
    if state == STATE_ASK and ask_dialog:
        ask_dialog.draw(screen, mp)

    # Barcode dialog
    if barcode_dialog:
        barcode_dialog.draw(screen, mp)

    # Recipe dialog
    if recipe_dialog:
        recipe_dialog.draw(screen, mp)

    # DONE banner
    if state == STATE_DONE:
        for p in done_parts: p.draw(screen)
        banner = pygame.Surface((W, 70), pygame.SRCALPHA)
        banner.fill((*NEON_GREEN, 50))
        screen.blit(banner, (0, 0))
        pygame.draw.line(screen, NEON_GREEN, (0, 70), (W, 70), 1)
        bx_off = W//2 - 120
        if bag_sprite and bag_sprite in sprites:
            big = pygame.transform.scale(sprites[bag_sprite], (48,48))
            screen.blit(big, (bx_off, 11))
            bx_off += 56
        ct_surf = f_xl.render(f"×{bag_count}  已加入冰箱！", True, NEON_GREEN)
        screen.blit(ct_surf, ct_surf.get_rect(midleft=(bx_off, 36)))
        ok_button.draw(screen)

    pygame.display.flip()

    # ══════ EVENTS ══════
    for event in pygame.event.get():
        if event.type == pygame.QUIT: running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if recipe_dialog: recipe_dialog = None
                else: running = False

        # PQ scroll
        if event.type == pygame.MOUSEWHEEL:
            if PQ_RECT.collidepoint(mp):
                PQ_SCROLL = max(0, PQ_SCROLL - event.y)
            elif REC_RECT.collidepoint(mp):
                pass
            elif SHOP_RECT.collidepoint(mp):
                shop_target = max(1, min(20, shop_target - event.y))

        if event.type == pygame.MOUSEBUTTONDOWN:
            pos = event.pos

            # PQ remove-by-hover
            if PQ_RECT.collidepoint(pos) and not recipe_dialog:
                items = fridge_pq.all_items()
                row_h = 52
                visible = (PQ_RECT.h - 46) // row_h
                for idx, item in enumerate(items):
                    vi = idx - PQ_SCROLL
                    if vi < 0 or vi >= visible: continue
                    ry = PQ_RECT.y+42 + vi*row_h
                    rr = pygame.Rect(PQ_RECT.x+6, ry, PQ_RECT.w-12, row_h-4)
                    del_btn = pygame.Rect(rr.right-28, rr.y+10, 22, 22)
                    if del_btn.collidepoint(pos) and rr.collidepoint(mp):
                        if item.get("id"):
                            db.log_consumption(item["name"], item["count"])
                            db.remove_item(item["id"])
                        fridge_pq.remove_by_name(item["name"])
                        break

            # Shopping prev/next recipe
            if shop_prev_btn and shop_prev_btn.collidepoint(pos):
                shop_rec_idx = max(0, shop_rec_idx-1)
            if shop_next_btn and shop_next_btn.collidepoint(pos):
                shop_rec_idx = min(len(recipes_cache)-1, shop_rec_idx+1) if recipes_cache else 0

            # New recipe button
            new_rec_btn.handle(event)
            if new_rec_btn.clicked:
                new_rec_btn.clicked = False
                recipe_dialog = RecipeEditDialog()

            # Mode toggle
            if MODE_BTN.collidepoint(pos) and not recipe_dialog:
                if state == STATE_BARCODE:
                    state = STATE_IDLE
                    barcode_overlay_rects.clear(); barcode_dialog = None
                    barcode_cooldown = 0.0; _bc_scan_active.clear()
                    while not barcode_raw_queue.empty():
                        try: barcode_raw_queue.get_nowait()
                        except: pass
                elif state == STATE_IDLE:
                    state = STATE_BARCODE; barcode_cooldown = 0.0
                    _bc_scan_active.set()

        # Recipe dialog
        if recipe_dialog:
            recipe_dialog.handle(event)
            if recipe_dialog.choice == "save":
                db.save_recipe(
                    recipe_dialog.name.strip(),
                    recipe_dialog.servings,
                    recipe_dialog.desc.strip(),
                    recipe_dialog.ings
                )
                recipes_cache[:] = db.load_recipes()
                recipe_dialog = None
            elif recipe_dialog.choice == "cancel":
                recipe_dialog = None
            continue   # don't process other events while dialog open

        # Barcode dialog
        if barcode_dialog:
            barcode_dialog.handle(event)
            if barcode_dialog.choice == "add":
                bname = barcode_dialog.name; bcount = barcode_dialog.count
                bcode = barcode_dialog.code
                bsprite = None
                for kw in bname.lower().split():
                    bsprite = find_sprite_key(kw)
                    if bsprite: break
                if not bsprite:
                    bsprite = find_sprite_key("box") or list(sprites.keys())[0] if sprites else None
                add_to_fridge(bname, bsprite, bcount, barcode=bcode)
                merged = False
                for i, entry in enumerate(shopping_queue):
                    if entry[2] == bname:
                        shopping_queue[i] = (entry[0], entry[1]+bcount, bname)
                        merged = True; break
                if not merged: shopping_queue.append((bsprite, bcount, bname))
                barcode_dialog = None; barcode_last_scan = ""; barcode_cooldown = 1.0
            elif barcode_dialog.choice == "skip":
                barcode_dialog = None; barcode_last_scan = ""; barcode_cooldown = 1.0

        # ASK dialog
        if state == STATE_ASK and ask_dialog:
            ask_dialog.handle(event)
            if ask_dialog.choice == 1:
                bag_sprite = cur_sprite
                flying.append(FlyingFruit(cur_sprite,
                    CAM_RECT.centerx, CAM_RECT.centery, BAG_X, BAG_Y+8))
                bag_count += 1; state = STATE_BAGGING
                ask_dialog = None; detect_cooldown = 1.2
            elif ask_dialog.choice == "many":
                bag_sprite = cur_sprite; state = STATE_BAGGING
                ask_dialog = None; detect_cooldown = 1.2
            elif ask_dialog.choice == "skip":
                state = STATE_IDLE; ask_dialog = None; detect_cooldown = 1.5

        # BAGGING: click bag
        if state == STATE_BAGGING and event.type == pygame.MOUSEBUTTONDOWN:
            brect = pygame.Rect(BAG_X-BAG_W//2-15, BAG_Y-30, BAG_W+30, BAG_H+45)
            if brect.collidepoint(event.pos):
                if not flying:
                    flying.append(FlyingFruit(cur_sprite,
                        CAM_RECT.centerx+random.randint(-20,20),
                        CAM_RECT.centery+random.randint(-25,25),
                        BAG_X, BAG_Y+8))
                    bag_count += 1
                else:
                    click_pending += 1
                    if click_timer <= 0: click_timer = CLICK_INTERVAL

        # OK button
        ok_button.handle(event)
        if ok_button.clicked:
            ok_button.clicked = False
            if state == STATE_DONE:
                # Save to DB
                merged = False
                for i, entry in enumerate(shopping_queue):
                    if entry[0] == bag_sprite and (len(entry)<3 or entry[2]==""):
                        shopping_queue[i] = (entry[0], entry[1]+bag_count, "")
                        merged = True; break
                if not merged: shopping_queue.append((bag_sprite, bag_count, ""))
                add_to_fridge(cur_label, bag_sprite, bag_count)
                bag_count = 0; bag_sprite = None
                flying.clear(); particles.clear(); done_parts.clear()
                click_pending = 0; detect_cooldown = 1.0; state = STATE_IDLE
            elif bag_count > 0:
                state = STATE_DONE; click_pending = 0
                for _ in range(80):
                    done_parts.append(Particle(W//2, H//2, explode=True))

pygame.quit()
exit()
