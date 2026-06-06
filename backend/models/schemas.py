from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------

class Scenario(str, Enum):
    family = "family"
    friends = "friends"


class ActivityCategory(str, Enum):
    aquarium    = "aquarium"
    park        = "park"
    museum      = "museum"
    kids_center = "kids_center"
    escape_room = "escape_room"
    exhibition  = "exhibition"
    citywalk    = "citywalk"


class ActivityPreference(str, Enum):
    nature   = "nature"    # 自然风光
    cultural = "cultural"  # 人文历史
    museum   = "museum"    # 博物馆
    social   = "social"    # 热闹聚会
    food     = "food"      # 以吃为主
    family   = "family"    # 亲子


class TravelMode(str, Enum):
    walk  = "walk"
    taxi  = "taxi"
    metro = "metro"
    bike  = "bike"


class NoiseLevel(str, Enum):
    quiet    = "quiet"
    moderate = "moderate"
    lively   = "lively"


class BookingStatus(str, Enum):
    success = "success"
    failed  = "failed"
    skipped = "skipped"


class ToolErrorCode(str, Enum):
    NO_SEAT        = "NO_SEAT"
    TOO_FAR        = "TOO_FAR"
    OVER_BUDGET    = "OVER_BUDGET"
    DELIVERY_UNAVAIL = "DELIVERY_UNAVAILABLE"
    CLOSED         = "CLOSED"
    SOLD_OUT       = "SOLD_OUT"


# ---------------------------------------------------------------------------
# 地理
# ---------------------------------------------------------------------------

class Coordinates(BaseModel):
    lat: float
    lng: float


# ---------------------------------------------------------------------------
# 场所
# ---------------------------------------------------------------------------

class Venue(BaseModel):
    id: str
    name: str
    category: ActivityCategory
    coordinates: Coordinates
    address: str
    distance_km: float
    price_per_person: int
    rating: float = Field(ge=0, le=5)
    opening_hours: str
    kids_friendly: bool = False
    indoor: bool = True
    tags: list[str] = []
    typical_visit_minutes: int = 90   # 由 tools/travel.py 按 category 填入


class Restaurant(BaseModel):
    id: str
    name: str
    cuisine: str
    coordinates: Coordinates
    address: str
    distance_km: float
    price_per_person: int
    rating: float = Field(ge=0, le=5)
    has_kids_menu: bool = False
    has_low_calorie_options: bool = False
    noise_level: NoiseLevel = NoiseLevel.moderate
    max_party_size: int = 10
    available_slots: list[str] = []
    tags: list[str] = []


# ---------------------------------------------------------------------------
# 可用性 & 路线
# ---------------------------------------------------------------------------

class AvailabilityResult(BaseModel):
    available: bool
    queue_minutes: int = 0
    next_available_slot: str | None = None
    error_code: ToolErrorCode | None = None
    retryable: bool = True
    message: str = ""


class TravelInfo(BaseModel):
    duration_minutes: int
    distance_km: float
    mode: TravelMode
    description: str = ""


# ---------------------------------------------------------------------------
# 约束
# ---------------------------------------------------------------------------

class ActivityConstraints(BaseModel):
    kids_friendly: bool = False
    min_age_limit: int = 0
    prefer_indoor: bool = False
    preferred_categories: list[ActivityCategory] = []


class RestaurantConstraints(BaseModel):
    has_kids_menu: bool = False
    has_low_calorie_options: bool = False
    noise_level: list[NoiseLevel] = []
    min_party_size: int = 1


class ConstraintSet(BaseModel):
    scenario: Scenario
    group_size: int
    city: str = "上海"
    start_time: str = "10:00"                # "HH:MM"
    duration_days: int = 1
    max_distance_km: float = 5.0
    budget_per_person: int = 200
    duration_hours: float = 5.0              # 单天游玩总时长（含餐饮）
    travel_modes: list[TravelMode] = [TravelMode.walk, TravelMode.taxi]
    food_focused: bool = False               # 食物偏好标签激活时为 True
    activity: ActivityConstraints = ActivityConstraints()
    restaurant: RestaurantConstraints = RestaurantConstraints()
    special_requirements: list[str] = []
    # 用户具体想吃的食物（冷启动/冷门检索）
    cuisine_request: str = ""                 # 用户原话，如 "爆啦兔头面"
    cuisine_keywords: list[str] = []          # 检索阶梯，具体→宽泛，如 ["兔头面", "川菜面馆", "特色面馆"]
    # 用户具体想去/想体验的活动（冷启动/冷门检索）
    venue_request: str = ""                   # 用户原话，如 "莫奈特展"
    venue_keywords: list[str] = []            # 检索阶梯，具体→宽泛，如 ["莫奈特展", "艺术展览", "美术馆"]


# ---------------------------------------------------------------------------
# 方案
# ---------------------------------------------------------------------------

class TimelineItem(BaseModel):
    day: int = 1                             # 第几天（多天行程必须）
    name: str
    address: str
    start_time: str                          # "14:00"
    end_time: str                            # "16:00"
    category: Literal["activity", "restaurant", "transport"]
    booking_required: bool = False
    estimated_cost: int = 0                  # 人均，元
    notes: str = ""
    map_uri: str = ""                        # 高德地图跳转链接，由后端按候选池真实坐标回填（LLM 勿填）


class Plan(BaseModel):
    id: str
    title: str
    summary: str
    timeline: list[TimelineItem]
    total_duration_minutes: int
    total_cost_estimate: int                 # 人均总价
    constraint_coverage: dict[str, bool] = {}
    score: float = Field(default=0.0, ge=0, le=5)


# ---------------------------------------------------------------------------
# 执行结果
# ---------------------------------------------------------------------------

class BookingResult(BaseModel):
    action: str
    target_name: str
    status: BookingStatus
    detail: str = ""
    cost: int = 0
    fallback_applied: bool = False


class ToolError(BaseModel):
    code: ToolErrorCode
    message: str
    retryable: bool = True
    context: dict = {}


# ---------------------------------------------------------------------------
# API 请求 / 响应
# ---------------------------------------------------------------------------

class UserRequest(BaseModel):
    """旧接口兼容（纯文字输入），Phase 8 替换为 PlanRequest。"""
    message: str
    location: Coordinates = Coordinates(lat=31.2304, lng=121.4737)


class PlanRequest(BaseModel):
    """结构化规划请求（来自新 UI），Phase 8 正式接入。"""
    # 结构化字段（来自 UI 控件）
    start_date:      date
    end_date:        date
    preferences:     list[ActivityPreference] = []
    max_distance_km: float = 5.0
    group_size:      int = 2
    duration_hours:  float = 5.0             # 每天活动时长（含餐饮）
    travel_modes:    list[TravelMode] = [TravelMode.taxi, TravelMode.metro]
    city:            str = "上海"
    # 自然语言补充（可为空）
    free_text:       str = ""


class FreeTextConstraints(BaseModel):
    """LLM 从 free_text 中提取的补充约束，仅覆盖有明确提及的字段。"""
    start_time:           str | None = None   # "10:00"
    duration_hours:       float | None = None
    budget_per_person:    int | None = None
    special_requirements: list[str] = []
    scenario:             Scenario | None = None
    cuisine_request:      str = ""            # 用户具体想吃的食物原话，如 "爆啦兔头面"
    cuisine_keywords:     list[str] = []      # 检索阶梯，从具体到宽泛，如 ["兔头面", "川菜面馆", "特色面馆"]
    venue_request:        str = ""            # 用户具体想去/想体验的活动原话，如 "莫奈特展"
    venue_keywords:       list[str] = []      # 检索阶梯，从具体到宽泛，如 ["莫奈特展", "艺术展览", "美术馆"]


class SessionResponse(BaseModel):
    session_id: str
    status: str = "created"


class ConfirmRequest(BaseModel):
    confirmed: bool
    selected_plan_id: str
    feedback: str = ""
