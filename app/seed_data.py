"""
seed_data.py — FridgeBud 示例数据
运行方式：python seed_data.py
自行建表，不需要先运行 fridgebud_v3.py。
重复运行安全（食材追加，配方 upsert）。
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "fridgebud.db"


def conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def ensure_tables(c):
    """建表（若不存在）并补齐缺失列，和主程序 _init/_migrate 逻辑一致。"""
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
    for table, cols in {
        "fridge_items": [
            ("unit",       "TEXT DEFAULT 'pcs'"),
            ("note",       "TEXT DEFAULT ''"),
            ("shelf_days", "INTEGER"),
        ],
        "user_history": [
            ("unit",      "TEXT DEFAULT 'pcs'"),
            ("last_used", "TEXT"),
        ],
    }.items():
        existing = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for col, defn in cols:
            if col not in existing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
                print(f"  [migration] {table}.{col} 已补齐")


FRIDGE_ITEMS = [
    ("西红柿",  5, "个",  7,  2),
    ("鸡蛋",   10, "个", 35,  0),
    ("大蒜",    2, "头", 60,  0),
    ("姜",      1, "块", 30,  5),
    ("葱",      3, "根",  7,  4),
    ("豆腐",    1, "块",  5,  3),
    ("白菜",    1, "颗", 14,  2),
    ("胡萝卜",  3, "根", 21,  0),
    ("土豆",    4, "个", 21,  7),
    ("菠菜",    1, "把",  5,  4),
    ("香菇",    6, "朵",  7,  0),
    ("洋葱",    2, "个", 30,  0),
    ("猪五花", 300, "g",  3,  0),
    ("鸡腿",    2, "个",  3,  1),
    ("虾",    200, "g",   2,  0),
    ("酱油",    1, "瓶", 180, 30),
    ("料酒",    1, "瓶", 180, 20),
    ("盐",      1, "袋", 365,  0),
    ("白糖",    1, "袋", 365,  0),
    ("豆瓣酱",  1, "瓶", 120, 10),
    ("牛奶",    2, "盒",   7,  2),
    ("淡奶油",  1, "盒",   7,  0),
]

RECIPES = [
    ("番茄炒鸡蛋", 2, "家常经典，酸甜下饭", [
        ("西红柿", 3, "个"), ("鸡蛋", 3, "个"),
        ("盐", 1, "少许"), ("白糖", 1, "少许"), ("葱", 1, "根"),
    ]),
    ("红烧肉", 4, "猪五花慢炖，入口即化", [
        ("猪五花", 500, "g"), ("酱油", 3, "勺"),
        ("料酒", 2, "勺"), ("白糖", 2, "勺"),
        ("姜", 3, "片"), ("葱", 2, "根"),
    ]),
    ("蒜炒白菜", 2, "快手素菜，三分钟出锅", [
        ("白菜", 1, "颗"), ("大蒜", 4, "瓣"), ("盐", 1, "少许"),
    ]),
    ("土豆丝", 2, "切细丝，醋溜或干煸都行", [
        ("土豆", 2, "个"), ("葱", 1, "根"), ("盐", 1, "少许"),
    ]),
    ("麻婆豆腐", 2, "四川风味，麻辣鲜香", [
        ("豆腐", 1, "块"), ("猪五花", 50, "g"), ("豆瓣酱", 1, "勺"),
        ("大蒜", 3, "瓣"), ("姜", 2, "片"), ("葱", 1, "根"), ("酱油", 1, "勺"),
    ]),
    ("香菇炒肉片", 3, "香菇鲜味渗入肉片，简单好吃", [
        ("香菇", 6, "朵"), ("猪五花", 200, "g"),
        ("酱油", 2, "勺"), ("料酒", 1, "勺"),
        ("大蒜", 2, "瓣"), ("姜", 2, "片"),
    ]),
    ("胡萝卜炒蛋", 2, "营养均衡，颜色好看", [
        ("胡萝卜", 2, "根"), ("鸡蛋", 2, "个"),
        ("葱", 1, "根"), ("盐", 1, "少许"),
    ]),
    ("蒜蓉菠菜", 2, "焯水快炒，保留绿色", [
        ("菠菜", 1, "把"), ("大蒜", 4, "瓣"),
        ("盐", 1, "少许"), ("酱油", 1, "少许"),
    ]),
    ("虾仁炒蛋", 2, "嫩滑鲜美，出锅快", [
        ("虾", 150, "g"), ("鸡蛋", 2, "个"),
        ("葱", 1, "根"), ("料酒", 1, "勺"), ("盐", 1, "少许"),
    ]),
    ("可乐鸡腿", 2, "甜口焖鸡，小孩最爱", [
        ("鸡腿", 2, "个"), ("酱油", 2, "勺"),
        ("料酒", 1, "勺"), ("白糖", 1, "勺"), ("姜", 3, "片"),
    ]),
    ("洋葱炒肉", 2, "洋葱提鲜，猪肉嫩滑", [
        ("洋葱", 1, "个"), ("猪五花", 150, "g"),
        ("酱油", 2, "勺"), ("料酒", 1, "勺"),
    ]),
    ("紫菜蛋花汤", 2, "两分钟快手汤", [
        ("鸡蛋", 1, "个"), ("葱", 1, "根"),
        ("盐", 1, "少许"), ("酱油", 1, "少许"),
    ]),
]


def seed():
    now = datetime.now()
    with conn() as c:
        ensure_tables(c)

        added = 0
        for name, count, unit, shelf, offset in FRIDGE_ITEMS:
            added_date  = now - timedelta(days=offset)
            expiry_date = added_date + timedelta(days=shelf)
            c.execute(
                "INSERT INTO fridge_items (name,count,unit,added_date,expiry_date,shelf_days,note) VALUES (?,?,?,?,?,?,'')",
                (name, count, unit, added_date.isoformat(), expiry_date.isoformat(), shelf)
            )
            c.execute(
                "INSERT INTO user_history (name,uses,last_used,unit) VALUES (?,1,?,?) "
                "ON CONFLICT(name) DO UPDATE SET uses=uses+1, last_used=excluded.last_used, unit=excluded.unit",
                (name, now.isoformat(), unit)
            )
            added += 1
        print(f"✓  冰箱食材：已写入 {added} 条")

        upserted = 0
        for rec_name, servings, desc, ingredients in RECIPES:
            cur = c.execute(
                "INSERT INTO recipes (name,servings,created_at) VALUES (?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET servings=excluded.servings",
                (rec_name, servings, now.isoformat())
            )
            rid = cur.lastrowid or c.execute(
                "SELECT id FROM recipes WHERE name=?", (rec_name,)
            ).fetchone()[0]
            c.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
            for ing_name, amount, ing_unit in ingredients:
                c.execute(
                    "INSERT INTO recipe_ingredients (recipe_id,ingredient,amount,unit) VALUES (?,?,?,?)",
                    (rid, ing_name, amount, ing_unit)
                )
            upserted += 1
        print(f"✓  配方：已写入 {upserted} 道菜")

    print(f"\n🎉  完成！启动 fridgebud_v3.py 即可看到数据。")
    print(f"   数据库：{DB_PATH.resolve()}")


if __name__ == "__main__":
    seed()
