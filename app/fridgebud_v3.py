"""
FridgeBud v3 — 极简手动录入版
• 无摄像头，键盘录入食材
• Autofill：餐馆词典优先级 + 历史记忆
• 拖拽：列表项拖到「完成」区域快速消耗
• SQLite 持久化：重启不丢数据
• 最少点击：Enter 录入，Backspace 删除，Tab 补全
"""

import pygame
import os
import threading
import queue
import sqlite3
import json
import heapq
import math
import random
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# ════════════════════════════════
#  CONFIG
# ════════════════════════════════
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
FRIDGE_TEMP_C  = 4
DB_PATH        = Path(__file__).parent.parent / "fridgebud.db"
SPRITE_PATH    = Path(__file__).parent.parent / "FreePixelFood" / "Assets" / "FreePixelFood" / "Sprite" / "Food"

# ════════════════════════════════
#  RESTAURANT INGREDIENT DICTIONARY
#  (score = how common in restaurants; higher = appear first in autofill)
# ════════════════════════════════
RESTAURANT_DICT = {
    # ── 蔬菜 Vegetables ──
    "洋葱": 98, "大蒜": 97, "姜": 96, "葱": 95, "芹菜": 90,
    "土豆": 92, "红薯": 85, "胡萝卜": 91, "白萝卜": 88, "西红柿": 94,
    "黄瓜": 89, "茄子": 86, "辣椒": 87, "青椒": 86, "西兰花": 88,
    "白菜": 90, "菠菜": 85, "生菜": 84, "莴笋": 80, "冬瓜": 82,
    "南瓜": 83, "豆芽": 85, "韭菜": 84, "蒜苗": 82, "香菜": 80,
    "木耳": 88, "金针菇": 85, "香菇": 90, "平菇": 83, "蘑菇": 85,
    "豆腐": 92, "油豆腐": 80, "腐竹": 78, "魔芋": 76,
    "花椰菜": 79, "芥蓝": 78, "油菜": 80, "空心菜": 79,
    "玉米": 85, "毛豆": 80, "四季豆": 82, "荷兰豆": 79, "豌豆": 78,
    # ── 肉类 Meat ──
    "猪肉": 95, "猪五花": 90, "猪里脊": 88, "排骨": 87, "猪蹄": 80,
    "牛肉": 93, "牛里脊": 88, "牛腩": 87, "羊肉": 85, "鸡肉": 94,
    "鸡腿": 90, "鸡胸": 88, "鸭肉": 82, "鸭腿": 80,
    "培根": 82, "火腿": 80, "香肠": 83, "腊肠": 78,
    # ── 海鲜 Seafood ──
    "虾": 90, "大虾": 88, "虾仁": 85, "螃蟹": 80, "鱿鱼": 82,
    "鱼": 88, "草鱼": 82, "鲈鱼": 84, "带鱼": 80, "鲫鱼": 82,
    "三文鱼": 83, "蛤蜊": 79, "花蛤": 78, "牡蛎": 78,
    # ── 蛋奶豆 Eggs/Dairy ──
    "鸡蛋": 98, "鸭蛋": 80, "皮蛋": 78, "牛奶": 85, "淡奶油": 80,
    "黄油": 78, "奶酪": 76, "酸奶": 82,
    # ── 主食原料 Staples ──
    "大米": 95, "面粉": 90, "面条": 88, "粉条": 82, "豆腐皮": 80,
    "糯米": 78, "玉米淀粉": 82, "土豆淀粉": 80,
    # ── 调味料 Condiments ──
    "盐": 99, "酱油": 97, "生抽": 96, "老抽": 90, "醋": 92,
    "白糖": 92, "料酒": 90, "花椒": 88, "八角": 85, "桂皮": 82,
    "豆瓣酱": 88, "豆豉": 80, "蚝油": 88, "鱼露": 78,
    "芝麻油": 85, "花生油": 90, "菜籽油": 88, "橄榄油": 82,
    "番茄酱": 85, "辣椒酱": 83, "甜面酱": 78, "腐乳": 76,
    "白胡椒": 85, "黑胡椒": 84, "孜然": 82, "辣椒粉": 84,
    # ── 水果 Fruits ──
    "苹果": 82, "香蕉": 80, "橙子": 80, "柠檬": 85, "西瓜": 78,
    "草莓": 80, "葡萄": 78, "芒果": 78, "菠萝": 76, "梨": 76,
    # ── 英文别名（for mixed input）──
    "onion": 98, "garlic": 97, "ginger": 96, "tomato": 94,
    "potato": 92, "carrot": 91, "cucumber": 89, "egg": 98,
    "chicken": 94, "pork": 95, "beef": 93, "shrimp": 90,
    "tofu": 92, "mushroom": 85, "cabbage": 90, "pepper": 87,
    "salt": 99, "soy sauce": 97, "vinegar": 92, "sugar": 92,
    "apple": 82, "banana": 80, "lemon": 85, "broccoli": 88,
    "spinach": 85, "lettuce": 84, "corn": 85, "milk": 85,
    "butter": 78, "flour": 90, "rice": 95,
}

# ════════════════════════════════
#  SHELF LIFE DATABASE
# ════════════════════════════════
SHELF_LIFE = {
    # vegetables
    "洋葱": 30, "大蒜": 60, "姜": 30, "葱": 7, "芹菜": 10,
    "土豆": 21, "红薯": 14, "胡萝卜": 21, "白萝卜": 14, "西红柿": 7,
    "黄瓜": 7, "茄子": 7, "辣椒": 10, "青椒": 10, "西兰花": 7,
    "白菜": 14, "菠菜": 5, "生菜": 5, "莴笋": 7, "冬瓜": 14,
    "南瓜": 21, "豆芽": 5, "韭菜": 5, "香菜": 5, "蒜苗": 7,
    "木耳": 5, "金针菇": 5, "香菇": 7, "平菇": 5, "蘑菇": 7,
    "豆腐": 5, "玉米": 5, "毛豆": 5, "四季豆": 7, "荷兰豆": 5,
    "花椰菜": 7, "油菜": 5, "空心菜": 3,
    # meat
    "猪肉": 3, "猪五花": 3, "猪里脊": 3, "排骨": 3, "猪蹄": 3,
    "牛肉": 4, "牛里脊": 4, "牛腩": 4, "羊肉": 3, "鸡肉": 3,
    "鸡腿": 3, "鸡胸": 3, "鸭肉": 3, "培根": 7, "香肠": 14,
    # seafood
    "虾": 2, "大虾": 2, "虾仁": 2, "鱿鱼": 2, "鱼": 2,
    "草鱼": 2, "鲈鱼": 2, "带鱼": 2, "三文鱼": 2, "蛤蜊": 2,
    # dairy/eggs
    "鸡蛋": 35, "牛奶": 7, "淡奶油": 7, "黄油": 60, "酸奶": 14,
    # staples / condiments (long shelf life)
    "大米": 180, "面粉": 180, "面条": 90, "盐": 365, "酱油": 365,
    "生抽": 365, "老抽": 365, "醋": 365, "白糖": 365, "料酒": 365,
    "豆瓣酱": 180, "蚝油": 180, "番茄酱": 90,
    # english aliases
    "onion": 30, "garlic": 60, "ginger": 30, "tomato": 7,
    "potato": 21, "carrot": 21, "cucumber": 7, "egg": 35,
    "chicken": 3, "pork": 3, "beef": 4, "shrimp": 2,
    "tofu": 5, "mushroom": 7, "cabbage": 14, "pepper": 10,
    "apple": 28, "banana": 5, "lemon": 21, "broccoli": 7,
    "spinach": 5, "lettuce": 5, "corn": 5, "milk": 7,
    "butter": 60, "flour": 180, "rice": 180,
}

def get_shelf_days(name: str) -> int:
    key = name.strip()
    if key in SHELF_LIFE:
        return SHELF_LIFE[key]
    key_low = key.lower()
    for k, v in SHELF_LIFE.items():
        if k.lower() == key_low or k in key or key in k:
            return v
    return 7

# ════════════════════════════════
#  SQLITE DATABASE
# ════════════════════════════════
class FridgeDB:
    def __init__(self, path=DB_PATH):
        self.path = str(path)
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self._conn() as c:
            # ── 建表（首次运行）──
            c.executescript("""
            CREATE TABLE IF NOT EXISTS fridge_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                count       REAL NOT NULL DEFAULT 1,
                unit        TEXT DEFAULT 'pcs',
                added_date  TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                shelf_days  INTEGER,
                note        TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS user_history (
                name        TEXT PRIMARY KEY,
                uses        INTEGER DEFAULT 1,
                last_used   TEXT,
                unit        TEXT DEFAULT 'pcs'
            );
            CREATE TABLE IF NOT EXISTS recipes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                servings    INTEGER DEFAULT 1,
                created_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recipe_ingredients (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id   INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
                ingredient  TEXT NOT NULL,
                amount      REAL NOT NULL,
                unit        TEXT DEFAULT 'pcs'
            );
            """)
            # ── Migration：给旧表补缺失列 ──
            self._migrate(c)

    # SQLite 没有 ALTER TABLE ADD COLUMN IF NOT EXISTS，
    # 要先查 PRAGMA table_info 看列名，再决定要不要 ALTER。
    def _migrate(self, conn):
        migrations = {
            "fridge_items": [
                ("unit",       "TEXT DEFAULT 'pcs'"),
                ("note",       "TEXT DEFAULT ''"),
                ("shelf_days", "INTEGER"),
            ],
            "user_history": [
                ("unit",      "TEXT DEFAULT 'pcs'"),
                ("last_used", "TEXT"),
            ],
        }
        for table, columns in migrations.items():
            existing = {
                row[1]   # column name is index 1 in PRAGMA result
                for row in conn.execute(f"PRAGMA table_info({table})")
            }
            for col_name, col_def in columns:
                if col_name not in existing:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"
                    )
                    print(f"[DB migration] {table}.{col_name} 已补齐")

    # ── fridge ──
    def save_item(self, item: dict) -> int:
        with self._conn() as c:
            cur = c.execute("""
                INSERT INTO fridge_items (name,count,unit,added_date,expiry_date,shelf_days,note)
                VALUES (?,?,?,?,?,?,?)
            """, (item["name"], item["count"], item.get("unit","pcs"),
                  item["added_date"].isoformat(), item["expiry_date"].isoformat(),
                  item["shelf_days"], item.get("note","")))
            self._bump_history(c, item["name"], item.get("unit","pcs"))
            return cur.lastrowid

    def _bump_history(self, conn, name, unit):
        conn.execute("""
            INSERT INTO user_history (name, uses, last_used, unit)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(name) DO UPDATE SET uses=uses+1, last_used=excluded.last_used,
                unit=excluded.unit
        """, (name, datetime.now().isoformat(), unit))

    def delete_item(self, item_id: int):
        with self._conn() as c:
            c.execute("DELETE FROM fridge_items WHERE id=?", (item_id,))

    def update_count(self, item_id: int, delta: float):
        with self._conn() as c:
            c.execute("UPDATE fridge_items SET count=MAX(0,count+?) WHERE id=?", (delta, item_id))

    def load_fridge(self) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM fridge_items WHERE count>0 ORDER BY expiry_date ASC"
            ).fetchall()
            return [{
                "id": r["id"], "name": r["name"],
                "count": r["count"], "unit": r["unit"],
                "added_date": datetime.fromisoformat(r["added_date"]),
                "expiry_date": datetime.fromisoformat(r["expiry_date"]),
                "shelf_days": r["shelf_days"], "note": r["note"],
            } for r in rows]

    # ── history / autofill ──
    def get_history(self) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT name, uses, unit FROM user_history ORDER BY uses DESC"
            ).fetchall()
            return [{"name": r["name"], "uses": r["uses"], "unit": r["unit"]} for r in rows]

    def load_recipes(self) -> list:
        with self._conn() as c:
            recs = c.execute("SELECT * FROM recipes ORDER BY name").fetchall()
            result = []
            for r in recs:
                ings = c.execute(
                    "SELECT * FROM recipe_ingredients WHERE recipe_id=?", (r["id"],)
                ).fetchall()
                result.append({
                    "id": r["id"], "name": r["name"], "servings": r["servings"],
                    "ingredients": [{"ingredient": i["ingredient"],
                                     "amount": i["amount"], "unit": i["unit"]} for i in ings]
                })
            return result

    def save_recipe(self, name, servings, ingredients):
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO recipes (name,servings,created_at) VALUES (?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET servings=excluded.servings",
                (name, servings, datetime.now().isoformat())
            )
            rid = cur.lastrowid or c.execute("SELECT id FROM recipes WHERE name=?", (name,)).fetchone()["id"]
            c.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
            for ing in ingredients:
                c.execute("INSERT INTO recipe_ingredients (recipe_id,ingredient,amount,unit) VALUES (?,?,?,?)",
                          (rid, ing["ingredient"], ing["amount"], ing.get("unit","pcs")))

db = FridgeDB()

# ════════════════════════════════
#  AUTOFILL ENGINE
# ════════════════════════════════
class AutofillEngine:
    """
    Priority = restaurant_score * 0.4 + history_uses * 2 (capped 60) + prefix_match * 30
    Sorted: exact prefix > substring > fuzzy
    """
    def __init__(self):
        self.history = {}   # name → uses
        self.history_unit = {}
        self._refresh()

    def _refresh(self):
        for h in db.get_history():
            self.history[h["name"]] = h["uses"]
            self.history_unit[h["name"]] = h["unit"]

    def score(self, name: str, query: str) -> float:
        q = query.lower()
        n = name.lower()
        base = RESTAURANT_DICT.get(name, 0) * 0.4
        hist = min(self.history.get(name, 0) * 2, 60)
        if n.startswith(q):
            pos = 40
        elif q in n:
            pos = 20
        else:
            pos = 0
        return base + hist + pos

    def suggest(self, query: str, limit=8) -> list:
        if len(query) < 1:
            return []
        q = query.lower()
        candidates = set()
        # from restaurant dict
        for name in RESTAURANT_DICT:
            n = name.lower()
            if q in n or n.startswith(q):
                candidates.add(name)
        # from history
        for name in self.history:
            n = name.lower()
            if q in n or n.startswith(q):
                candidates.add(name)
        ranked = sorted(candidates, key=lambda x: -self.score(x, query))
        return ranked[:limit]

    def recall_unit(self, name: str) -> str:
        return self.history_unit.get(name, "")

    def notify_used(self, name: str, unit: str):
        self.history[name] = self.history.get(name, 0) + 1
        self.history_unit[name] = unit

autofill = AutofillEngine()

# ════════════════════════════════
#  PYGAME INIT
# ════════════════════════════════
pygame.init()
W, H = 1280, 780
screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
pygame.display.set_caption("FridgeBud v3")
clock = pygame.time.Clock()

# ── Fonts ──
def sysfont(size, bold=False):
    return pygame.font.SysFont(
        "microsoftyahei,noto sans sc,wenquanyi micro hei,helvetica neue,arial",
        size, bold=bold
    )

F_TITLE  = sysfont(22, bold=True)
F_BODY   = sysfont(17)
F_SMALL  = sysfont(14)
F_TINY   = sysfont(12)
F_INPUT  = sysfont(20, bold=True)
F_NUM    = sysfont(28, bold=True)
F_HINT   = sysfont(13)

# ── Sprites ──
sprites = {}
if SPRITE_PATH.exists():
    for f in SPRITE_PATH.iterdir():
        if f.suffix == ".png":
            try:
                img = pygame.image.load(str(f)).convert_alpha()
                sprites[f.stem.lower()] = img
            except: pass

ICON_MAP = {
    "洋葱":"onion","大蒜":"garlic","姜":"ginger","葱":"onion","土豆":"potato",
    "胡萝卜":"carrot","西红柿":"tomato","黄瓜":"cucumber","茄子":"eggplant",
    "辣椒":"pepper","青椒":"pepper","西兰花":"broccoli","白菜":"cabbage",
    "菠菜":"spinach","生菜":"lettuce","玉米":"corn","香菇":"mushroom",
    "豆腐":"tofu","鸡蛋":"egg","苹果":"apple","香蕉":"banana",
    "橙子":"orange","柠檬":"lemon","西瓜":"watermelon","草莓":"strawberry",
    "葡萄":"grapes","芒果":"mango","梨":"pear","菠萝":"pineapple",
    "桃":"peach","樱桃":"cherry","石榴":"pomegranate","猪肉":"pork",
    "牛肉":"beef","鸡肉":"chicken","大米":"rice",
}
FOOD_EMOJIS = {
    "洋葱":"🧅","大蒜":"🧄","姜":"🫚","葱":"🌿","土豆":"🥔","胡萝卜":"🥕",
    "西红柿":"🍅","黄瓜":"🥒","茄子":"🍆","辣椒":"🌶️","西兰花":"🥦",
    "白菜":"🥬","菠菜":"🥬","玉米":"🌽","香菇":"🍄","豆腐":"🟫",
    "鸡蛋":"🥚","苹果":"🍎","香蕉":"🍌","橙子":"🍊","柠檬":"🍋",
    "西瓜":"🍉","草莓":"🍓","葡萄":"🍇","芒果":"🥭","梨":"🍐",
    "菠萝":"🍍","桃":"🍑","樱桃":"🍒","猪肉":"🥩","牛肉":"🥩",
    "鸡肉":"🍗","鸡腿":"🍗","虾":"🍤","鱼":"🐟","螃蟹":"🦀",
    "牛奶":"🥛","黄油":"🧈","鸡蛋":"🥚","盐":"🧂","大米":"🍚",
    "onion":"🧅","garlic":"🧄","potato":"🥔","carrot":"🥕","tomato":"🍅",
    "cucumber":"🥒","eggplant":"🍆","broccoli":"🥦","cabbage":"🥬",
    "mushroom":"🍄","egg":"🥚","apple":"🍎","banana":"🍌","lemon":"🍋",
    "shrimp":"🍤","chicken":"🍗","beef":"🥩","pork":"🥩","milk":"🥛",
    "rice":"🍚","salt":"🧂","corn":"🌽","spinach":"🥬","pepper":"🌶️",
}
def get_emoji(name): return FOOD_EMOJIS.get(name, "🥡")

def get_sprite(name, size):
    key = ICON_MAP.get(name, name.lower())
    if key in sprites:
        return pygame.transform.scale(sprites[key], (size, size))
    for k in sprites:
        if name.lower() in k or k in name.lower():
            return pygame.transform.scale(sprites[k], (size, size))
    return None

# ════════════════════════════════
#  PALETTE  — warm cream × earthy
# ════════════════════════════════
BG         = (245, 241, 234)
SURFACE    = (255, 252, 247)
SURFACE2   = (238, 233, 224)
BORDER     = (200, 192, 178)
BORDER_DK  = (160, 148, 130)
ACCENT     = ( 42,  95,  78)   # deep teal-green
ACCENT2    = (210,  90,  40)   # terracotta
ACCENT3    = (180, 140,  40)   # amber
TEXT1      = ( 28,  26,  22)
TEXT2      = ( 90,  84,  74)
TEXT3      = (150, 142, 128)
RED_SOFT   = (200,  60,  50)
RED_BG     = (255, 235, 232)
AMBER_BG   = (255, 248, 225)
GREEN_BG   = (225, 245, 232)
GREEN_DK   = ( 30, 130,  75)
WHITE      = (255, 255, 255)
BLACK      = (  0,   0,   0)
SHADOW     = ( 0,   0,   0,  18)
INPUT_FOCUS= ( 42,  95,  78)

def col_alpha(col, a):
    s = pygame.Surface((1,1), pygame.SRCALPHA)
    s.fill((*col, a))
    return s

def draw_rounded(surf, col, rect, r=10, border=0, bcol=None):
    pygame.draw.rect(surf, col, rect, border_radius=r)
    if border and bcol:
        pygame.draw.rect(surf, bcol, rect, border, border_radius=r)

def draw_shadow(surf, rect, r=10, blur=8, alpha=25):
    for i in range(blur, 0, -1):
        a = int(alpha * (i/blur)**2)
        sr = pygame.Rect(rect.x-i//2+2, rect.y-i//2+3, rect.w+i, rect.h+i)
        s = pygame.Surface((sr.w, sr.h), pygame.SRCALPHA)
        pygame.draw.rect(s, (0,0,0,a), (0,0,sr.w,sr.h), border_radius=r+i//2)
        surf.blit(s, sr.topleft)

# ════════════════════════════════
#  PRIORITY QUEUE
# ════════════════════════════════
class FridgePQ:
    def __init__(self):
        self._h = []; self._c = 0
    def push(self, item):
        self._c += 1
        heapq.heappush(self._h, (item["expiry_date"], self._c, item))
    def all_items(self):
        return [x[2] for x in sorted(self._h)]
    def remove_id(self, iid):
        for i,(e,c,it) in enumerate(self._h):
            if it["id"] == iid:
                self._h.pop(i); heapq.heapify(self._h); return it
        return None
    def __len__(self): return len(self._h)

fridge_pq = FridgePQ()
for _it in db.load_fridge():
    fridge_pq.push(_it)
print(f"[DB] 恢复 {len(fridge_pq)} 条")

# ════════════════════════════════
#  DRAG STATE
# ════════════════════════════════
class DragState:
    def __init__(self):
        self.active  = False
        self.item    = None     # the fridge item dict
        self.start_x = 0
        self.start_y = 0
        self.x       = 0
        self.y       = 0
        self.ghost_alpha = 0
        self.row_idx = -1

drag = DragState()

# ════════════════════════════════
#  INPUT WIDGET
# ════════════════════════════════
class InputBar:
    def __init__(self, rect):
        self.rect     = pygame.Rect(rect)
        self.text     = ""
        self.count    = 1.0
        self.unit     = ""
        self.focused  = True
        self.field    = "name"   # "name" | "count" | "unit"
        self.cursor_t = 0.0
        self.suggestions = []
        self.sel_idx  = -1       # selected suggestion index
        self.tab_filled = False  # whether tab was used

    def set_focus(self, field):
        self.field = field
        self.cursor_t = 0.0

    def get_active_text(self):
        if self.field == "name":   return self.text
        if self.field == "count":  return str(self.count)
        if self.field == "unit":   return self.unit
        return ""

    def handle_key(self, event):
        if event.key == pygame.K_TAB:
            # accept first suggestion
            if self.suggestions:
                chosen = self.suggestions[self.sel_idx if self.sel_idx >= 0 else 0]
                self.text = chosen
                recalled_unit = autofill.recall_unit(chosen)
                if recalled_unit:
                    self.unit = recalled_unit
                self.suggestions = []
                self.sel_idx = -1
                self.tab_filled = True
                self.set_focus("count")
            else:
                # cycle fields
                fields = ["name","count","unit"]
                idx = fields.index(self.field)
                self.set_focus(fields[(idx+1) % len(fields)])
            return None

        if event.key == pygame.K_DOWN:
            if self.suggestions:
                self.sel_idx = min(self.sel_idx+1, len(self.suggestions)-1)
            elif self.field == "count":
                self.count = max(0.5, round(self.count - 0.5, 1))
            return None

        if event.key == pygame.K_UP:
            if self.suggestions:
                self.sel_idx = max(0, self.sel_idx-1)
            elif self.field == "count":
                self.count = min(99, round(self.count + 0.5, 1))
            return None

        if event.key == pygame.K_ESCAPE:
            self.text = ""; self.suggestions = []; self.sel_idx = -1
            self.count = 1.0; self.unit = ""
            self.set_focus("name")
            return None

        if event.key == pygame.K_RETURN:
            return self._submit()

        # Backspace
        if event.key == pygame.K_BACKSPACE:
            if self.field == "name":
                self.text = self.text[:-1]
                self._update_suggestions()
            elif self.field == "count":
                s = str(self.count)
                self.count = float(s[:-1]) if len(s) > 1 else 1.0
                try: self.count = float(str(self.count)[:-1]) if len(str(self.count))>1 else 1.0
                except: self.count = 1.0
            elif self.field == "unit":
                self.unit = self.unit[:-1]
            return None

        if not event.unicode:
            return None

        ch = event.unicode
        if self.field == "name":
            self.text += ch
            self._update_suggestions()
        elif self.field == "count":
            candidate = str(self.count) + ch if ch.isdigit() or ch=="." else ""
            if candidate:
                try: self.count = float(candidate); self.count = min(99, self.count)
                except: pass
        elif self.field == "unit":
            if len(self.unit) < 8:
                self.unit += ch
        return None

    def _update_suggestions(self):
        self.suggestions = autofill.suggest(self.text) if self.text else []
        self.sel_idx = 0 if self.suggestions else -1

    def _submit(self):
        name = self.text.strip()
        if not name:
            return None
        # auto-fill unit from recall if empty
        if not self.unit:
            self.unit = autofill.recall_unit(name) or "pcs"
        item = {
            "name": name,
            "count": self.count,
            "unit": self.unit or "pcs",
            "added_date": datetime.now(),
            "expiry_date": datetime.now() + timedelta(days=get_shelf_days(name)),
            "shelf_days": get_shelf_days(name),
            "note": "",
        }
        item["id"] = db.save_item(item)
        fridge_pq.push(item)
        autofill.notify_used(name, self.unit or "pcs")
        added = {"name": name}
        # reset
        self.text = ""; self.count = 1.0; self.unit = ""
        self.suggestions = []; self.sel_idx = -1
        self.tab_filled = False
        self.set_focus("name")
        return added

    def click(self, pos):
        """Handle mouse click inside bar — set field focus"""
        # We'll compute the sub-rects in draw() and store them
        if hasattr(self, "_name_rect") and self._name_rect.collidepoint(pos):
            self.set_focus("name"); return True
        if hasattr(self, "_count_rect") and self._count_rect.collidepoint(pos):
            self.set_focus("count"); return True
        if hasattr(self, "_unit_rect") and self._unit_rect.collidepoint(pos):
            self.set_focus("unit"); return True
        return False

    def draw(self, surf, mp):
        r = self.rect
        draw_shadow(surf, r, r=14, blur=10, alpha=20)
        draw_rounded(surf, SURFACE, r, r=14)
        draw_rounded(surf, ACCENT if self.focused else BORDER, r, r=14, border=2, bcol=ACCENT if self.focused else BORDER)

        PAD = 14
        field_y = r.y + (r.h - 28) // 2

        # --- NAME field ---
        name_w = r.w - 240 - PAD*3
        name_rect = pygame.Rect(r.x+PAD, r.y+8, name_w, r.h-16)
        self._name_rect = name_rect
        name_active = self.field == "name"
        if name_active:
            draw_rounded(surf, GREEN_BG, name_rect, r=8)
            draw_rounded(surf, ACCENT, name_rect, r=8, border=2, bcol=ACCENT)
        disp_text = self.text
        cursor_vis = name_active and (int(time.time()*2) % 2 == 0)
        if cursor_vis: disp_text += "|"
        ts = F_INPUT.render(disp_text if disp_text else "", True,
                             TEXT1 if self.text else TEXT3)
        hint_ts = F_BODY.render("输入食材名..." if not self.text else "", True, TEXT3)
        surf.blit(hint_ts, (name_rect.x+10, name_rect.y + (name_rect.h-hint_ts.get_height())//2))
        surf.blit(ts, (name_rect.x+10, name_rect.y + (name_rect.h-ts.get_height())//2))

        # --- COUNT field ---
        cx = r.x + PAD*2 + name_w
        count_rect = pygame.Rect(cx, r.y+8, 90, r.h-16)
        self._count_rect = count_rect
        count_active = self.field == "count"
        draw_rounded(surf, AMBER_BG if count_active else SURFACE2, count_rect, r=8)
        if count_active:
            draw_rounded(surf, ACCENT2, count_rect, r=8, border=2, bcol=ACCENT2)
        cnt_s = F_NUM.render(str(self.count).rstrip("0").rstrip(".") if self.count != int(self.count) else str(int(self.count)),
                              True, ACCENT2)
        surf.blit(cnt_s, cnt_s.get_rect(center=count_rect.center))

        # --- UNIT field ---
        ux = cx + 90 + PAD
        unit_rect = pygame.Rect(ux, r.y+8, 80, r.h-16)
        self._unit_rect = unit_rect
        unit_active = self.field == "unit"
        draw_rounded(surf, SURFACE2, unit_rect, r=8)
        if unit_active:
            draw_rounded(surf, BORDER_DK, unit_rect, r=8, border=2, bcol=ACCENT3)
        unit_disp = self.unit or (autofill.recall_unit(self.text) or "单位")
        us = F_BODY.render(unit_disp, True, TEXT2 if self.unit else TEXT3)
        surf.blit(us, us.get_rect(center=unit_rect.center))

        # --- ADD button ---
        add_rect = pygame.Rect(ux+80+PAD, r.y+8, 70, r.h-16)
        hov = add_rect.collidepoint(mp)
        draw_rounded(surf, ACCENT if not hov else (30,75,60), add_rect, r=8)
        ts_add = F_BODY.render("添加 ↵", True, WHITE)
        surf.blit(ts_add, ts_add.get_rect(center=add_rect.center))
        self._add_rect = add_rect

        # ── Hint line ──
        hints = [
            "Tab 补全  ·  ↑↓ 选择  ·  Enter 添加  ·  Esc 清空"
        ]
        hs = F_HINT.render(hints[0], True, TEXT3)
        surf.blit(hs, (r.x+PAD, r.bottom+4))

        # ── Suggestions dropdown ──
        if self.suggestions and name_active:
            self._draw_suggestions(surf, name_rect, mp)

    def _draw_suggestions(self, surf, anchor_rect, mp):
        ROW = 36
        W_s = anchor_rect.w
        sx  = anchor_rect.x
        sy  = anchor_rect.bottom + 4
        box = pygame.Rect(sx, sy, W_s, len(self.suggestions)*ROW + 8)
        draw_shadow(surf, box, r=10, blur=8)
        draw_rounded(surf, SURFACE, box, r=10)
        draw_rounded(surf, BORDER, box, r=10, border=1, bcol=BORDER)

        for i, name in enumerate(self.suggestions):
            ry  = sy + 4 + i*ROW
            rr  = pygame.Rect(sx+4, ry, W_s-8, ROW-2)
            hov = rr.collidepoint(mp)
            sel = i == self.sel_idx
            if sel or hov:
                draw_rounded(surf, GREEN_BG, rr, r=7)
                draw_rounded(surf, ACCENT, rr, r=7, border=1, bcol=ACCENT)
            em = get_emoji(name)
            es = F_BODY.render(em, True, TEXT1)
            surf.blit(es, (rr.x+8, ry + (ROW-es.get_height())//2 - 1))
            ns = F_BODY.render(name, True, TEXT1 if not sel else ACCENT)
            surf.blit(ns, (rr.x+34, ry + (ROW-ns.get_height())//2))
            # score indicator
            sc = RESTAURANT_DICT.get(name, 0)
            hist = autofill.history.get(name, 0)
            tag = "常用" if hist > 0 else "热门" if sc > 85 else ""
            if tag:
                ts2 = F_TINY.render(tag, True, ACCENT3)
                surf.blit(ts2, (rr.right-ts2.get_width()-10, ry+(ROW-ts2.get_height())//2))
        # store rects for click handling
        self._sugg_rects = [pygame.Rect(sx+4, sy+4+i*ROW, W_s-8, ROW-2)
                            for i in range(len(self.suggestions))]

    def click_suggestion(self, pos):
        if not hasattr(self, "_sugg_rects"):
            return
        for i, r in enumerate(self._sugg_rects):
            if r.collidepoint(pos):
                chosen = self.suggestions[i]
                self.text = chosen
                recalled = autofill.recall_unit(chosen)
                if recalled: self.unit = recalled
                self.suggestions = []
                self.sel_idx = -1
                self.set_focus("count")
                return True
        return False

    def click_add(self, pos):
        return hasattr(self, "_add_rect") and self._add_rect.collidepoint(pos)


# ════════════════════════════════
#  FRIDGE LIST RENDERER
# ════════════════════════════════
FRIDGE_SCROLL = 0
ROW_H = 58
FRIDGE_RECT  = pygame.Rect(0, 0, 0, 0)   # set in loop
TRASH_ZONE   = pygame.Rect(0, 0, 0, 0)   # set in loop
hovered_row  = -1

def draw_fridge_list(surf, items, mp, drag_state):
    global FRIDGE_SCROLL, hovered_row
    r = FRIDGE_RECT
    now = datetime.now()

    draw_shadow(surf, r, r=14, blur=8, alpha=15)
    draw_rounded(surf, SURFACE, r, r=14)
    draw_rounded(surf, BORDER, r, r=14, border=1, bcol=BORDER)

    # Title
    title_r = pygame.Rect(r.x, r.y, r.w, 46)
    draw_rounded(surf, SURFACE2, title_r, r=14)
    pygame.draw.rect(surf, SURFACE2, (r.x, r.y+14, r.w, 32))
    pygame.draw.line(surf, BORDER, (r.x+1, r.y+46), (r.right-1, r.y+46))
    ts = F_TITLE.render(f"冰箱清单  ({len(items)})", True, TEXT1)
    surf.blit(ts, (r.x+18, r.y+13))
    sort_hint = F_HINT.render("按过期日期排序 · 拖拽到右侧删除", True, TEXT3)
    surf.blit(sort_hint, (r.right-sort_hint.get_width()-14, r.y+17))

    if not items:
        es = F_BODY.render("冰箱空空如也 — 快去添加食材！", True, TEXT3)
        surf.blit(es, es.get_rect(center=(r.centerx, r.centery+20)))
        return

    # Clip list
    clip = pygame.Rect(r.x+1, r.y+47, r.w-2, r.h-48)
    surf.set_clip(clip)

    visible = (r.h - 50) // ROW_H
    max_scroll = max(0, len(items) - visible)
    FRIDGE_SCROLL = min(FRIDGE_SCROLL, max_scroll)

    hovered_row = -1

    for idx, item in enumerate(items):
        vi = idx - FRIDGE_SCROLL
        if vi < 0 or vi >= visible + 1: continue

        ry = r.y + 50 + vi * ROW_H

        # Skip the item being dragged (it's drawn as ghost)
        if drag_state.active and drag_state.item and drag_state.item["id"] == item["id"]:
            # draw empty placeholder
            ph = pygame.Rect(r.x+10, ry+2, r.w-20, ROW_H-4)
            s = pygame.Surface((ph.w, ph.h), pygame.SRCALPHA)
            s.fill((0,0,0,8))
            pygame.draw.rect(s, BORDER, (0,0,ph.w,ph.h), 1, border_radius=9)
            surf.blit(s, ph.topleft)
            continue

        days_left = (item["expiry_date"] - now).days
        row_r = pygame.Rect(r.x+10, ry+2, r.w-20, ROW_H-4)
        is_hov = row_r.collidepoint(mp)
        if is_hov:
            hovered_row = idx

        # Row background by urgency
        if days_left < 0:
            bg, border_c, status_c = RED_BG, RED_SOFT, RED_SOFT
            status = f"已过期 {-days_left}d"
        elif days_left <= 2:
            bg, border_c, status_c = (255,240,225), ACCENT2, ACCENT2
            status = f"⚡ {days_left}天"
        elif days_left <= 5:
            bg, border_c, status_c = AMBER_BG, ACCENT3, ACCENT3
            status = f"{days_left}天"
        else:
            bg, border_c, status_c = (SURFACE2 if not is_hov else (228,230,222)), BORDER, GREEN_DK
            status = f"{days_left}天"

        if is_hov:
            draw_shadow(surf, row_r, r=9, blur=4, alpha=12)
        draw_rounded(surf, bg, row_r, r=9)
        draw_rounded(surf, border_c, row_r, r=9, border=1, bcol=border_c)

        # Rank badge
        rank_s = F_TINY.render(f"#{idx+1}", True, TEXT3)
        surf.blit(rank_s, (row_r.x+6, row_r.y+6))

        # Emoji / Sprite icon
        em = get_emoji(item["name"])
        sp = get_sprite(item["name"], 28)
        if sp:
            surf.blit(sp, (row_r.x+28, row_r.y + (ROW_H-4-28)//2))
        else:
            em_s = F_BODY.render(em, True, TEXT1)
            surf.blit(em_s, (row_r.x+28, row_r.y + (ROW_H-4-em_s.get_height())//2))

        # Name
        disp = item["name"]
        ns = F_BODY.render(disp, True, TEXT1)
        surf.blit(ns, (row_r.x+64, row_r.y+8))

        # Count × unit
        cnt_str = f"×{item['count']:.0f}" if item['count']==int(item['count']) else f"×{item['count']}"
        unit_str = f" {item['unit']}"
        cs = F_SMALL.render(cnt_str + unit_str, True, ACCENT2)
        surf.blit(cs, (row_r.x+64, row_r.y+28))

        # Expiry date
        exp_s = F_SMALL.render(item["expiry_date"].strftime("%m/%d"), True, TEXT3)
        surf.blit(exp_s, (row_r.right-140, row_r.y+16))

        # Status badge
        st_surf = F_SMALL.render(status, True, status_c)
        st_bg   = pygame.Rect(row_r.right-70, row_r.y+10, st_surf.get_width()+14, 22)
        draw_rounded(surf, (*status_c, 25), st_bg, r=6)
        pygame.draw.rect(surf, status_c, st_bg, 1, border_radius=6)
        surf.blit(st_surf, (st_bg.x+7, st_bg.y+3))

        # Hover: quick action buttons
        if is_hov and not drag_state.active:
            # +1 / -1 buttons (tight)
            btn_w = 28
            dec_r = pygame.Rect(row_r.right-130, row_r.y+14, btn_w, 22)
            inc_r = pygame.Rect(row_r.right-98,  row_r.y+14, btn_w, 22)
            draw_rounded(surf, WHITE, dec_r, r=5, border=1, bcol=BORDER_DK)
            draw_rounded(surf, WHITE, inc_r, r=5, border=1, bcol=BORDER_DK)
            ds = F_SMALL.render("−", True, TEXT2)
            ins = F_SMALL.render("+", True, TEXT2)
            surf.blit(ds, ds.get_rect(center=dec_r.center))
            surf.blit(ins, ins.get_rect(center=inc_r.center))
            item["_dec_rect"] = dec_r
            item["_inc_rect"] = inc_r

            # drag hint
            dh = F_HINT.render("⠿ 拖拽", True, TEXT3)
            surf.blit(dh, (row_r.x+6, row_r.y+ROW_H-20))

    surf.set_clip(None)

    # Scroll indicators
    if FRIDGE_SCROLL > 0:
        arr = F_HINT.render("▲ 上滚", True, TEXT3)
        surf.blit(arr, (r.right-60, r.y+50))
    if FRIDGE_SCROLL < max_scroll:
        arr = F_HINT.render("▼ 下滚", True, TEXT3)
        surf.blit(arr, (r.right-60, r.bottom-16))


# ════════════════════════════════
#  TRASH / CONSUME ZONE
# ════════════════════════════════
def draw_trash_zone(surf, drag_state):
    r = TRASH_ZONE
    is_target = drag_state.active
    if is_target:
        col_bg = RED_BG
        col_bd = RED_SOFT
        alpha_boost = 255
    else:
        col_bg = SURFACE2
        col_bd = BORDER
        alpha_boost = 80

    draw_shadow(surf, r, r=14, blur=6, alpha=10)
    s = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
    s.fill((*col_bg, alpha_boost if is_target else 120))
    surf.blit(s, r.topleft)
    pygame.draw.rect(surf, col_bd, r, 2 if is_target else 1, border_radius=14)

    # Dashed border when dragging
    if is_target:
        dash_len = 12; gap = 6; t_now = time.time()
        phase = int(t_now * 60) % (dash_len+gap)
        for side in ["top","bot","left","right"]:
            if side == "top":
                pts = [(r.x+i, r.y) for i in range(0, r.w, dash_len+gap)]
                for p in pts:
                    pygame.draw.line(surf, RED_SOFT, (p[0]-phase, p[1]),
                                     (p[0]-phase+dash_len, p[1]), 2)
            elif side == "bot":
                pts = [(r.x+i, r.bottom) for i in range(0, r.w, dash_len+gap)]
                for p in pts:
                    pygame.draw.line(surf, RED_SOFT, (p[0]+phase, p[1]),
                                     (p[0]+phase-dash_len, p[1]), 2)

    icon = "🗑️" if is_target else "🗑"
    is2 = F_BODY.render(icon, True, RED_SOFT if is_target else TEXT3)
    surf.blit(is2, is2.get_rect(center=(r.centerx, r.centery-18)))
    lbl = F_SMALL.render("拖拽至此", True, RED_SOFT if is_target else TEXT3)
    surf.blit(lbl, lbl.get_rect(center=(r.centerx, r.centery+2)))
    sub = F_HINT.render("删除食材", True, TEXT3)
    surf.blit(sub, sub.get_rect(center=(r.centerx, r.centery+18)))


# ════════════════════════════════
#  RECIPE PANEL
# ════════════════════════════════
recipes_cache = db.load_recipes()
rec_scroll    = 0
REC_RECT      = pygame.Rect(0,0,0,0)

def compute_servings(rec):
    stock = {}
    for it in fridge_pq.all_items():
        k = it["name"].lower()
        stock[k] = stock.get(k,0) + it["count"]
    if not rec["ingredients"]: return 0
    mins = []
    for ing in rec["ingredients"]:
        iname = ing["ingredient"].lower()
        have = sum(v for k,v in stock.items() if iname in k or k in iname)
        if ing["amount"] > 0:
            mins.append(int(have / ing["amount"]))
        else:
            mins.append(999)
    return min(mins) if mins else 0

def draw_recipe_panel(surf, mp):
    global rec_scroll
    r = REC_RECT
    draw_shadow(surf, r, r=14, blur=6, alpha=12)
    draw_rounded(surf, SURFACE, r, r=14)
    draw_rounded(surf, BORDER, r, r=14, border=1, bcol=BORDER)

    # Title row
    ts = F_TITLE.render(f"配方 ({len(recipes_cache)})", True, TEXT1)
    surf.blit(ts, (r.x+16, r.y+12))

    if not recipes_cache:
        es = F_BODY.render("还没有配方", True, TEXT3)
        surf.blit(es, es.get_rect(center=r.center))
        return

    ROW = 48
    visible = (r.h - 46) // ROW
    max_scroll = max(0, len(recipes_cache)-visible)
    rec_scroll = min(rec_scroll, max_scroll)

    clip = pygame.Rect(r.x+1, r.y+46, r.w-2, r.h-47)
    surf.set_clip(clip)

    for i, rec in enumerate(recipes_cache):
        vi = i - rec_scroll
        if vi < 0 or vi >= visible+1: continue
        ry  = r.y+48 + vi*ROW
        rr  = pygame.Rect(r.x+10, ry, r.w-20, ROW-4)
        hov = rr.collidepoint(mp)
        draw_rounded(surf, (230,225,215) if hov else SURFACE2, rr, r=8)
        draw_rounded(surf, BORDER_DK if hov else BORDER, rr, r=8, border=1, bcol=BORDER_DK if hov else BORDER)
        ns = F_BODY.render(rec["name"][:14], True, TEXT1)
        surf.blit(ns, (rr.x+10, rr.y+6))
        ings = " · ".join(i2["ingredient"] for i2 in rec["ingredients"][:3])
        if len(rec["ingredients"])>3: ings+="…"
        is_ = F_HINT.render(ings, True, TEXT3)
        surf.blit(is_, (rr.x+10, rr.y+26))
        srv = compute_servings(rec)
        col = GREEN_DK if srv>0 else RED_SOFT
        ss = F_SMALL.render(f"可做{srv}份", True, col)
        surf.blit(ss, (rr.right-ss.get_width()-10, rr.y+14))

    surf.set_clip(None)


# ════════════════════════════════
#  ANALYTICS PANEL
# ════════════════════════════════
ANA_RECT = pygame.Rect(0,0,0,0)

def draw_analytics(surf):
    r = ANA_RECT
    draw_shadow(surf, r, r=14, blur=6, alpha=12)
    draw_rounded(surf, SURFACE, r, r=14)
    draw_rounded(surf, BORDER, r, r=14, border=1, bcol=BORDER)
    ts = F_TITLE.render("概览", True, TEXT1)
    surf.blit(ts, (r.x+16, r.y+12))

    items = fridge_pq.all_items()
    now   = datetime.now()
    expired = [i for i in items if (i["expiry_date"]-now).days < 0]
    urgent  = [i for i in items if 0 <= (i["expiry_date"]-now).days <= 2]
    safe    = [i for i in items if (i["expiry_date"]-now).days > 2]
    total_count = sum(i["count"] for i in items)

    rows = [
        ("总品类", f"{len(items)} 种", ACCENT),
        ("总数量", f"{total_count:.0f} 件", ACCENT),
        ("已过期", f"{len(expired)} 种", RED_SOFT if expired else GREEN_DK),
        ("即将到期", f"{len(urgent)} 种", ACCENT2 if urgent else GREEN_DK),
        ("状态良好", f"{len(safe)} 种", GREEN_DK),
    ]

    row_h = (r.h - 50) // len(rows)
    for i, (label, val, col) in enumerate(rows):
        ry = r.y+46 + i*row_h
        lbs = F_SMALL.render(label, True, TEXT2)
        surf.blit(lbs, (r.x+16, ry+row_h//2-lbs.get_height()//2))
        vs = F_BODY.render(val, True, col)
        surf.blit(vs, (r.right-vs.get_width()-16, ry+row_h//2-vs.get_height()//2))
        if i < len(rows)-1:
            pygame.draw.line(surf, BORDER, (r.x+10, ry+row_h), (r.right-10, ry+row_h))


# ════════════════════════════════
#  DRAG GHOST RENDERER
# ════════════════════════════════
def draw_drag_ghost(surf, drag_state):
    if not drag_state.active or not drag_state.item: return
    item = drag_state.item
    ghost_w, ghost_h = 220, 48
    gx = drag_state.x - ghost_w//2
    gy = drag_state.y - ghost_h//2

    # Check if over trash zone
    over_trash = TRASH_ZONE.collidepoint(drag_state.x, drag_state.y)
    bg_col = RED_BG if over_trash else SURFACE
    bd_col = RED_SOFT if over_trash else ACCENT

    s = pygame.Surface((ghost_w, ghost_h), pygame.SRCALPHA)
    s.fill((*bg_col, 230))
    pygame.draw.rect(s, bd_col, (0,0,ghost_w,ghost_h), 2, border_radius=10)

    em = get_emoji(item["name"])
    em_s = F_BODY.render(em, True, TEXT1)
    s.blit(em_s, (10, (ghost_h-em_s.get_height())//2))
    ns = F_BODY.render(item["name"][:12], True, TEXT1)
    s.blit(ns, (40, 8))
    cnt = f"×{item['count']:.0f} {item['unit']}"
    cs = F_SMALL.render(cnt, True, TEXT2)
    s.blit(cs, (40, 28))

    surf.blit(s, (gx, gy))


# ════════════════════════════════
#  RECENT ADDITIONS TICKER
# ════════════════════════════════
recent_adds = []   # list of (name, t)

def add_to_recent(name):
    recent_adds.insert(0, (name, time.time()))
    if len(recent_adds) > 5: recent_adds.pop()

def draw_recent(surf, r):
    now = time.time()
    ys = r.y
    for name, t in recent_adds[:3]:
        age = now - t
        if age > 6: continue
        alpha = int(255 * max(0, 1 - age/4))
        em = get_emoji(name)
        txt = F_HINT.render(f"{em} {name} ✓", True, GREEN_DK)
        s = pygame.Surface((txt.get_width()+20, txt.get_height()+8), pygame.SRCALPHA)
        s.fill((225,245,232,alpha))
        pygame.draw.rect(s, (GREEN_DK[0],GREEN_DK[1],GREEN_DK[2],alpha),
                         (0,0,s.get_width(),s.get_height()), 1, border_radius=6)
        txt2 = pygame.Surface(txt.get_size(), pygame.SRCALPHA)
        txt2.blit(txt, (0,0))
        txt2.set_alpha(alpha)
        surf.blit(s, (r.x, ys))
        surf.blit(txt2, (r.x+10, ys+4))
        ys += s.get_height() + 4


# ════════════════════════════════
#  MAIN LOOP
# ════════════════════════════════
input_bar = InputBar((0,0,0,0))   # rect set in loop
running   = True
toast_msg = ""
toast_t   = 0.0

# Stars (static background dots)
STARS = [(random.randint(0, 1400), random.randint(0, 820),
          random.uniform(0.3, 1.0)) for _ in range(60)]

while running:
    dt = clock.tick(60) / 1000.0
    mp = pygame.mouse.get_pos()
    WW, WH = screen.get_size()

    # ── Layout (responsive) ──
    PAD = 16
    INPUT_H = 60
    TOP_BAR_H = 52

    # Input bar: full-width top area
    input_bar.rect = pygame.Rect(PAD, TOP_BAR_H + PAD, WW - PAD*2, INPUT_H)

    # Main content below input bar
    CONTENT_TOP = TOP_BAR_H + PAD + INPUT_H + 28   # +28 for hint row
    CONTENT_H   = WH - CONTENT_TOP - PAD

    LIST_W   = int((WW - PAD*4) * 0.52)
    RIGHT_W  = WW - PAD*3 - LIST_W
    TRASH_W  = 120
    REC_H    = int(CONTENT_H * 0.52)
    ANA_H    = CONTENT_H - REC_H - PAD

    FRIDGE_RECT.update(PAD, CONTENT_TOP, LIST_W, CONTENT_H)
    TRASH_ZONE.update(PAD + LIST_W + PAD, CONTENT_TOP, TRASH_W, 120)
    REC_RECT.update(PAD + LIST_W + PAD + TRASH_W + PAD, CONTENT_TOP, RIGHT_W - TRASH_W - PAD, REC_H)
    ANA_RECT.update(PAD + LIST_W + PAD + TRASH_W + PAD, CONTENT_TOP + REC_H + PAD, RIGHT_W - TRASH_W - PAD, ANA_H)

    # ── Draw BG ──
    screen.fill(BG)
    # subtle grain texture
    for sx, sy, b in STARS:
        a = int(b * 30)
        pygame.draw.circle(screen, (180, 170, 155), (int(sx % WW), int(sy % WH)), 1)

    # ── Title bar ──
    title_bar = pygame.Rect(0, 0, WW, TOP_BAR_H)
    draw_rounded(screen, SURFACE, title_bar, r=0)
    pygame.draw.line(screen, BORDER, (0, TOP_BAR_H), (WW, TOP_BAR_H))
    logo_s = F_TITLE.render("❄  FridgeBud", True, ACCENT)
    screen.blit(logo_s, (20, 14))
    now_s  = F_SMALL.render(datetime.now().strftime("%Y-%m-%d  %H:%M"), True, TEXT3)
    screen.blit(now_s, (WW//2 - now_s.get_width()//2, 18))
    temp_s = F_SMALL.render(f"🌡 {FRIDGE_TEMP_C}°C", True, TEXT2)
    screen.blit(temp_s, (WW-temp_s.get_width()-20, 18))

    # ── Input bar ──
    input_bar.draw(screen, mp)
    input_bar.cursor_t += dt

    # ── Fridge list ──
    items = fridge_pq.all_items()
    draw_fridge_list(screen, items, mp, drag)

    # ── Trash zone ──
    draw_trash_zone(screen, drag)

    # ── Recipe panel ──
    draw_recipe_panel(screen, mp)

    # ── Analytics ──
    draw_analytics(screen)

    # ── Recent add ticker ──
    draw_recent(screen, pygame.Rect(FRIDGE_RECT.x, FRIDGE_RECT.bottom+6, 300, 80))

    # ── Drag ghost ──
    draw_drag_ghost(screen, drag)

    # ── Toast ──
    if toast_msg and time.time() - toast_t < 2.5:
        alpha = int(255 * min(1, (2.5-(time.time()-toast_t))/0.5))
        ts = F_BODY.render(toast_msg, True, ACCENT)
        tb = pygame.Rect(WW//2-ts.get_width()//2-14, WH-60, ts.get_width()+28, 38)
        s2 = pygame.Surface((tb.w, tb.h), pygame.SRCALPHA)
        s2.fill((*GREEN_BG, min(230, alpha)))
        pygame.draw.rect(s2, (*ACCENT, alpha), (0,0,tb.w,tb.h), 2, border_radius=10)
        screen.blit(s2, tb.topleft)
        screen.blit(ts, (tb.x+14, tb.y+9))

    pygame.display.flip()

    # ════════════════════════════════
    #  EVENTS
    # ════════════════════════════════
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        # ── Keyboard ──
        if event.type == pygame.KEYDOWN:
            if not input_bar.focused:
                input_bar.focused = True
            result = input_bar.handle_key(event)
            if result:   # item was added
                add_to_recent(result["name"])
                toast_msg = f"✓  已添加 {result['name']}"
                toast_t   = time.time()

        # ── Scroll ──
        if event.type == pygame.MOUSEWHEEL:
            if FRIDGE_RECT.collidepoint(mp):
                FRIDGE_SCROLL = max(0, FRIDGE_SCROLL - event.y)

        # ── Mouse down ──
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos

            # Input bar interactions
            if input_bar.rect.collidepoint(pos):
                input_bar.focused = True
                if input_bar.click(pos):
                    pass
                elif input_bar.click_add(pos):
                    r2 = input_bar._submit()
                    if r2:
                        add_to_recent(r2["name"])
                        toast_msg = f"✓  已添加 {r2['name']}"
                        toast_t   = time.time()
            else:
                # Suggestion dropdown click
                if input_bar.suggestions:
                    input_bar.click_suggestion(pos)
                else:
                    input_bar.focused = FRIDGE_RECT.collidepoint(pos)

            # Fridge list clicks
            if FRIDGE_RECT.collidepoint(pos):
                visible = (FRIDGE_RECT.h - 50) // ROW_H
                for idx, item in enumerate(items):
                    vi = idx - FRIDGE_SCROLL
                    if vi < 0 or vi >= visible: continue
                    ry = FRIDGE_RECT.y + 50 + vi*ROW_H
                    row_r = pygame.Rect(FRIDGE_RECT.x+10, ry+2, FRIDGE_RECT.w-20, ROW_H-4)

                    # +/- buttons
                    if item.get("_dec_rect") and item["_dec_rect"].collidepoint(pos):
                        if item["count"] > 1:
                            item["count"] -= 1
                            db.update_count(item["id"], -1)
                        else:
                            # Remove entirely
                            db.delete_item(item["id"])
                            fridge_pq.remove_id(item["id"])
                            toast_msg = f"已移除 {item['name']}"
                            toast_t   = time.time()
                        break
                    if item.get("_inc_rect") and item["_inc_rect"].collidepoint(pos):
                        item["count"] += 1
                        db.update_count(item["id"], 1)
                        break

                    # Start drag
                    if row_r.collidepoint(pos) and not item.get("_dec_rect") and not item.get("_inc_rect"):
                        drag.active  = True
                        drag.item    = item
                        drag.row_idx = idx
                        drag.start_x = pos[0]; drag.start_y = pos[1]
                        drag.x       = pos[0]; drag.y       = pos[1]
                        break

        # ── Mouse drag ──
        if event.type == pygame.MOUSEMOTION and drag.active:
            drag.x = event.pos[0]; drag.y = event.pos[1]

        # ── Mouse up ──
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and drag.active:
            drop_pos = (drag.x, drag.y)
            if TRASH_ZONE.collidepoint(drop_pos) and drag.item:
                # Delete item
                iid = drag.item["id"]
                name = drag.item["name"]
                db.delete_item(iid)
                fridge_pq.remove_id(iid)
                toast_msg = f"🗑  已移除 {name}"
                toast_t   = time.time()
            # reset drag
            drag.active  = False
            drag.item    = None
            drag.row_idx = -1

pygame.quit()
exit()