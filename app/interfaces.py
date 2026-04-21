"""
interfaces.py — FridgeBud 接口层
所有数据模型 (dataclass) 和行为契约 (Protocol) 定义在此。
其他模块只 import，不重复定义。
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


# ════════════════════════════════════════════════════════
#  DATA MODELS  —  纯数据，无方法，可序列化
# ════════════════════════════════════════════════════════

@dataclass
class FridgeItem:
    name:        str
    count:       float
    unit:        str
    added_date:  datetime
    expiry_date: datetime
    shelf_days:  int
    id:          int  = -1          # -1 = 尚未写入 DB
    note:        str  = ""

    @property
    def days_left(self) -> int:
        return (self.expiry_date - datetime.now()).days

    @property
    def is_expired(self) -> bool:
        return self.days_left < 0

    def __lt__(self, other: FridgeItem) -> bool:   # 让 heapq 可以比较
        return self.expiry_date < other.expiry_date


@dataclass
class RecipeIngredient:
    ingredient: str
    amount:     float
    unit:       str = "pcs"


@dataclass
class Recipe:
    name:        str
    servings:    int
    ingredients: list[RecipeIngredient] = field(default_factory=list)
    id:          int = -1
    description: str = ""


@dataclass
class HistoryEntry:
    name:      str
    uses:      int
    unit:      str
    last_used: datetime


@dataclass
class ShoppingItem:
    ingredient: str
    need:       float
    have:       float
    buy:        float
    unit:       str

    @property
    def is_sufficient(self) -> bool:
        return self.have >= self.need


# ──  aliases ──────────────────────────────────────
SuggestionList  = list[str]          # autofill 候选词列表
ShoppingPlan    = list[ShoppingItem] # 采购方案


# ════════════════════════════════════════════════════════
#  REPOSITORY PROTOCOLS  —  数据存取契约
# ════════════════════════════════════════════════════════

@runtime_checkable
class IFridgeRepository(Protocol):
    """冰箱食材的持久化接口。SQLiteDB 实现它，MockDB 也可以实现它（用于测试）。"""

    @abstractmethod
    def save(self, item: FridgeItem) -> int:
        """写入并返回新 id。"""
        ...

    @abstractmethod
    def delete(self, item_id: int) -> None:
        ...

    @abstractmethod
    def update_count(self, item_id: int, delta: float) -> None:
        ...

    @abstractmethod
    def load_all(self) -> list[FridgeItem]:
        """按 expiry_date ASC 返回所有 count > 0 的条目。"""
        ...


@runtime_checkable
class IRecipeRepository(Protocol):

    @abstractmethod
    def save(self, recipe: Recipe) -> int:
        ...

    @abstractmethod
    def delete(self, recipe_id: int) -> None:
        ...

    @abstractmethod
    def load_all(self) -> list[Recipe]:
        ...


@runtime_checkable
class IHistoryRepository(Protocol):

    @abstractmethod
    def bump(self, name: str, unit: str) -> None:
        """记录一次使用，若不存在则创建。"""
        ...

    @abstractmethod
    def load_all(self) -> list[HistoryEntry]:
        ...


# ════════════════════════════════════════════════════════
#  ENGINE PROTOCOLS  —  业务逻辑契约
# ════════════════════════════════════════════════════════

@runtime_checkable
class IAutofillEngine(Protocol):

    @abstractmethod
    def suggest(self, query: str, limit: int = 8) -> SuggestionList:
        """返回按优先级排序的候选词列表。"""
        ...

    @abstractmethod
    def recall_unit(self, name: str) -> str:
        """返回该食材上次使用的单位，无记录则返回空字符串。"""
        ...

    @abstractmethod
    def notify_used(self, name: str, unit: str) -> None:
        """用户确认添加后调用，更新内存权重。"""
        ...


@runtime_checkable
class IShelfLifeDB(Protocol):

    @abstractmethod
    def get_days(self, name: str) -> int:
        """返回估算保质天数。"""
        ...


@runtime_checkable
class IRecipeEngine(Protocol):

    @abstractmethod
    def compute_servings(self, recipe: Recipe, stock: dict[str, float]) -> int:
        """根据当前库存计算可做份数。"""
        ...

    @abstractmethod
    def compute_shopping_plan(
        self,
        recipe: Recipe,
        stock: dict[str, float],
        target_servings: int,
    ) -> ShoppingPlan:
        ...


# ════════════════════════════════════════════════════════
#  UI PROTOCOLS  —  界面组件契约
# ════════════════════════════════════════════════════════

@runtime_checkable
class IPanel(Protocol):
    """所有 UI 面板实现的最小接口（pygame 版）。"""

    @abstractmethod
    def update(self, dt: float) -> None:
        """每帧调用，dt 单位秒。"""
        ...

    @abstractmethod
    def draw(self, surface) -> None:
        ...

    @abstractmethod
    def handle_event(self, event) -> None:
        ...


@runtime_checkable
class IInputPanel(IPanel, Protocol):
    """录入栏额外暴露的信号。"""

    @abstractmethod
    def on_item_submitted(self, item: FridgeItem) -> None:
        """子类实现：用户按 Enter/点添加后触发。"""
        ...


@runtime_checkable
class IDraggable(Protocol):
    """支持拖拽的组件。"""

    @abstractmethod
    def start_drag(self, item: FridgeItem, pos: tuple[int, int]) -> None:
        ...

    @abstractmethod
    def update_drag(self, pos: tuple[int, int]) -> None:
        ...

    @abstractmethod
    def end_drag(self, pos: tuple[int, int]) -> None:
        """松手时调用，组件自行决定是否触发删除/移动。"""
        ...
