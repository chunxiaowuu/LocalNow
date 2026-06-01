from __future__ import annotations

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
    aquarium = "aquarium"
    park = "park"
    museum = "museum"
    kids_center = "kids_center"
    escape_room = "escape_room"
    exhibition = "exhibition"
    citywalk = "citywalk"


class TravelMode(str, Enum):
    walk = "walk"
    taxi = "taxi"
    metro = "metro"
    bike = "bike"


class NoiseLevel(str, Enum):
    quiet = "quiet"
    moderate = "moderate"
    lively = "lively"


class BookingStatus(str, Enum):
    success = "success"
    failed = "failed"
    skipped = "skipped"


class ToolErrorCode(str, Enum):
    NO_SEAT = "NO_SEAT"
    TOO_FAR = "TOO_FAR"
    OVER_BUDGET = "OVER_BUDGET"
    DELIVERY_UNAVAIL = "DELIVERY_UNAVAILABLE"
    CLOSED = "CLOSED"
    SOLD_OUT = "SOLD_OUT"


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
    available_slots: list[str] = []     # ["17:30", "18:00", "18:30"]
    tags: list[str] = []


# ---------------------------------------------------------------------------
# 可用性 & 路线
# ---------------------------------------------------------------------------

class AvailabilityResult(BaseModel):
    available: bool
    queue_minutes: int = 0
    next_available_slot: str | None = None
    error_code: ToolErrorCode | None = None
    retryable: bool = True   # False 时 replan 换地点，True 时换时间段重试
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
    max_distance_km: float = 5.0
    budget_per_person: int = 200
    duration_hours: float = 5.0
    travel_modes: list[TravelMode] = [TravelMode.walk, TravelMode.taxi]
    activity: ActivityConstraints = ActivityConstraints()
    restaurant: RestaurantConstraints = RestaurantConstraints()
    special_requirements: list[str] = []   # 自由文本，如"需要生日布置"


# ---------------------------------------------------------------------------
# 方案
# ---------------------------------------------------------------------------

class TimelineItem(BaseModel):
    name: str
    address: str
    start_time: str                 # "14:00"
    end_time: str                   # "16:00"
    category: Literal["activity", "restaurant", "transport"]
    booking_required: bool = False
    estimated_cost: int = 0         # 人均，元
    notes: str = ""


class Plan(BaseModel):
    id: str
    title: str
    summary: str
    timeline: list[TimelineItem]
    total_duration_minutes: int
    total_cost_estimate: int        # 人均总价
    constraint_coverage: dict[str, bool] = {}   # {"kids_friendly": True, ...}
    score: float = Field(default=0.0, ge=0, le=5)   # LLM 使用 0-5 分制


# ---------------------------------------------------------------------------
# 执行结果
# ---------------------------------------------------------------------------

class BookingResult(BaseModel):
    action: str                     # "订座", "购票", "发消息"
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
# API 请求 / 响应（FastAPI 用）
# ---------------------------------------------------------------------------

class UserRequest(BaseModel):
    message: str
    location: Coordinates = Coordinates(lat=31.2304, lng=121.4737)  # 默认上海


class SessionResponse(BaseModel):
    session_id: str
    status: str = "created"


class ConfirmRequest(BaseModel):
    confirmed: bool
    selected_plan_id: str
