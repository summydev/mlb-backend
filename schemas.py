from pydantic import BaseModel, EmailStr, Field
from typing import Literal, List, Optional
from datetime import date
 
 
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
    type: str # enum: nova | pip | luna | zap
    level: int
    xp: int
    xp_to_next: int
    mood: str # enum: energised | happy | neutral | tired | sad

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
    color: Literal["mint", "peach"] # Spec says mint = #3CFFC8, peach = #FF8A65 [cite: 159]

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
    confidence_score: float # Float 0-1. App shows warning if < 0.75 [cite: 149]

class SolveFeedbackRequest(BaseModel):
    helpful: bool
    flag_reason: Optional[str] = None