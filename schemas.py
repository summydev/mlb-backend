from pydantic import BaseModel, EmailStr, Field
from typing import Literal, List, Optional
from datetime import date, datetime
from uuid import UUID
from enum import Enum
 
# ==========================================
# AUTH & USER SETTINGS SCHEMAS
# ==========================================
class UserRegister(BaseModel):
    name: str = Field(..., min_length=2, max_length=60)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)

class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=72)

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict

class TokenRefreshRequest(BaseModel):
    refresh_token: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=8, max_length=72)

class UserProfileUpdate(BaseModel):
    # Based on the handoff doc: university, professional, high_school, self_improvement
    study_goal: str

class PetAdoptionRequest(BaseModel):
    # Only allow these exact 4 strings
    pet_type: Literal["nova", "pip", "luna", "zap"] 
    
    # The Regex pattern ^[a-zA-Z0-9 \-']+$ enforces the character rules perfectly
    pet_name: str = Field(
        ...,
        min_length=1, 
        max_length=20,
        pattern=r"^[a-zA-Z0-9 \-']+$", 
        description="Letters, numbers, spaces, hyphens, and apostrophes only."
    )

class FirstSessionUpdate(BaseModel):
    is_first_session: bool

# ==========================================
# DASHBOARD SCHEMAS (SCREEN 3)
# ==========================================
class UserDashboardInfo(BaseModel):
    first_name: str 
    is_first_session: bool 

class PetDashboardInfo(BaseModel):
    name: str
    type: str 
    level: int
    xp: int
    xp_to_next: int
    mood: str 
    xp_history: List[int] # <-- ADD THIS LINE
    
class StreakInfo(BaseModel):
    days: int
    active_today: bool

class Quest(BaseModel):
    id: str
    title: str
    type: str # "coop" or "solo"
    progress: int
    target: int
    members_count: Optional[int] = None 

class TodayPlanSession(BaseModel):
    id: str
    subject: str
    duration_mins: int
    mode: str # "flashcard", "feynman", "review"

class DashboardResponse(BaseModel):
    user: UserDashboardInfo
    pet: PetDashboardInfo
    quests: List[Quest]
    today_plan: List[TodayPlanSession]
    streak: StreakInfo
    greeting: str


# ==========================================
# STUDY PLAN SCHEMAS (SCREEN 9)
# ==========================================
class PlanGoal(BaseModel):
    subject: str
    deadline: date

class PlanStats(BaseModel):
    days_remaining: int
    daily_target_mins: int
    topics_count: int

class WeekDay(BaseModel):
    date: str # e.g., "2026-04-13"
    day_label: str # e.g., "MON"
    has_session: bool
    session_type: Literal["study", "review", "rest"]

class SessionDetail(BaseModel):
    id: str
    date: str
    time: str # e.g., "14:00"
    subject: str
    duration_mins: int
    mode: Literal["flashcard", "feynman", "review"]
    priority: Literal["normal", "high", "weak_area"]
    completed: bool

class Nudge(BaseModel):
    message: str
    action: Literal["reschedule", "reduce", "add"]
    session_id: Optional[str] = None

class PlanResponse(BaseModel):
    goal: PlanGoal
    stats: PlanStats
    week: List[WeekDay]
    sessions: List[SessionDetail]
    nudge: Optional[Nudge] = None

# Input schemas for the POST/PATCH routes
class PlanGenerateRequest(BaseModel):
    goal: str
    deadline: date

class SessionUpdateRequest(BaseModel):
    scheduled_time: Optional[str] = None
    duration_mins: Optional[int] = None
    skipped: Optional[bool] = None

class PlanApproveRequest(BaseModel):
    approved: bool


 
# ==========================================
# AI SOLVE SCHEMAS (SCREEN 10)
# ==========================================
class SolveRequest(BaseModel):
    question_text: Optional[str] = None
    question_image_base64: Optional[str] = None
    subject: Optional[str] = None

class HighlightTerm(BaseModel):
    term: str
    color: Literal["mint", "peach"] # Spec says mint = #3CFFC8, peach = #FF8A65

class SolutionStep(BaseModel):
    step_number: int
    text: str
    highlight_terms: List[HighlightTerm] = []

class CanvasLink(BaseModel):
    node_id: str
    node_label: str
    canvas_id: str

class SolveResponse(BaseModel):
    solution_id: str
    steps: List[SolutionStep]
    canvas_links: List[CanvasLink]
    confidence_score: float # Float 0-1. App shows warning if < 0.75

class SolveFeedbackRequest(BaseModel):
    helpful: bool
    flag_reason: Optional[str] = None

# ==========================================
# CANVAS TAB SCHEMAS (SCREEN 5)
# ==========================================
# --- Requests ---
class NodeCreate(BaseModel):
    label: str = Field(..., max_length=40)
    x: float
    y: float
    size: Literal["small", "medium", "large"] = "medium"
    is_hero: bool = False
    is_weak: bool = False

class NodeUpdate(BaseModel):
    label: Optional[str] = Field(None, max_length=40)
    x: Optional[float] = None
    y: Optional[float] = None
    size: Optional[Literal["small", "medium", "large"]] = None
    is_weak: Optional[bool] = None

class ConnectionCreate(BaseModel):
    from_node_id: UUID
    to_node_id: UUID
    label: Optional[str] = None

class CanvasCreate(BaseModel):
    name: str
    subject: str
    source_type: Literal["notes", "upload", "manual"] = "manual"
    source_id: Optional[int] = None # Links to Note ID if generated from notes

# --- Responses ---
class NodeResponse(BaseModel):
    id: UUID
    label: str
    x: float
    y: float
    size: Literal["small", "medium", "large"]
    is_hero: bool
    is_weak: bool
    definition: Optional[str] = None
    card_id: Optional[int] = None

class ConnectionResponse(BaseModel):
    id: UUID
    from_node_id: UUID
    to_node_id: UUID
    label: Optional[str] = None

class CanvasResponse(BaseModel):
    id: UUID
    name: str
    subject: str
    node_count: int
    weak_node_count: int
    thumbnail_url: Optional[str] = None
    source_type: str
    source_id: Optional[int] = None
    last_studied_at: Optional[datetime] = None
    created_at: datetime
    is_public: bool
    
    # These arrays will be populated when viewing the Infinite Canvas
    nodes: List[NodeResponse] = []
    connections: List[ConnectionResponse] = []

class CanvasStatusResponse(BaseModel):
    status: Literal["ready", "processing", "failed"]
    node_count: int
    nodes: List[NodeResponse] = []
# ==========================================
# COLLECTIONS SCHEMAS
# ==========================================

class VisibilityEnum(str, Enum):
    private = "private"
    shared = "shared"
    public = "public"

class ItemTypeEnum(str, Enum):
    note = "note"
    set = "set"
    canvas = "canvas"

# --- Sub-models ---
class CollectionItem(BaseModel):
    item_id: str  # Handles both Note IDs (int) and Canvas IDs (UUID)
    item_type: ItemTypeEnum
    position: int

class AccessUser(BaseModel):
    user_id: int  
    email: str
    granted_at: datetime
    granted_by: int 

class PendingRequest(BaseModel):
    request_id: int 
    user_id: int    
    username: str
    email: str
    message: Optional[str] = None
    requested_at: datetime

# --- Request Schemas (Incoming Data) ---
class CollectionCreate(BaseModel):
    title: str = Field(..., max_length=60)
    subject: str
    visibility: VisibilityEnum
    description: Optional[str] = Field(None, max_length=300)
    cover_emoji: Optional[str] = None
    item_ids: List[str] = []
    item_types: List[str] = [] # Added this so the backend knows what type each ID is

class CollectionUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=60)
    description: Optional[str] = Field(None, max_length=300)
    subject: Optional[str] = None
    visibility: Optional[VisibilityEnum] = None
    cover_emoji: Optional[str] = None

class ItemReorder(BaseModel):
    item_id: str 
    position: int

class ItemReorderRequest(BaseModel):
    positions: List[ItemReorder]

class AccessRequestCreate(BaseModel):
    message: Optional[str] = Field(None, max_length=120)

# --- Response Schemas (Outgoing Data) ---
class CollectionResponse(BaseModel):
    collection_id: int 
    owner_id: int      
    title: str
    description: Optional[str]
    subject: str
    cover_emoji: Optional[str]
    visibility: VisibilityEnum
    item_count: int
    share_token: str
    save_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CollectionDetailResponse(CollectionResponse):
    items: List[CollectionItem] = []
    access_list: List[AccessUser] = []
    pending_requests: List[PendingRequest] = []