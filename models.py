from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import date, datetime
from enum import Enum

# ==========================================
# ENUMS
# ==========================================

class DifficultyLevel(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"

# ==========================================
# USER & PET MODELS (ONBOARDING)
# ==========================================

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)
    hashed_password: str
    is_verified: bool = False
    
    # Profile Settings
    study_goal: Optional[str] = None
    is_first_session: bool = True
    
    # Relationships (Links to other tables)
    pets: List["Pet"] = Relationship(back_populates="user")
    quests: List["Quest"] = Relationship(back_populates="user")
    study_plans: List["StudyPlan"] = Relationship(back_populates="user")
    study_sets: List["StudySet"] = Relationship(back_populates="user")

class Pet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    pet_type: str
    pet_name: str
    level: int = 1
    xp: int = 0
    
    # Relationship back to the User
    user: Optional["User"] = Relationship(back_populates="pets")

# ==========================================
# DASHBOARD & STUDY PLAN MODELS (SCREEN 3 & 9)
# ==========================================

class Quest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    title: str
    type: str # "coop" or "solo"
    progress: int = 0
    target: int
    members_count: Optional[int] = None
    
    # Relationship back to the User
    user: Optional["User"] = Relationship(back_populates="quests")

class StudyPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    subject: str
    deadline: date
    is_approved: bool = False
    
    # Relationships
    user: Optional["User"] = Relationship(back_populates="study_plans")
    sessions: List["StudySession"] = Relationship(back_populates="plan", cascade_delete=True)

class StudySession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="studyplan.id")
    user_id: int = Field(foreign_key="user.id")
    
    date: str # Stored as a string YYYY-MM-DD for easy API formatting
    time: Optional[str] = None # e.g., "14:00"
    subject: str
    duration_mins: int
    mode: str # "flashcard", "feynman", "review"
    priority: str # "normal", "high", "weak_area"
    completed: bool = False
    skipped: bool = False
    
    # Relationship back to the StudyPlan
    plan: Optional["StudyPlan"] = Relationship(back_populates="sessions")

class DailyActivity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    date: str # Stored as YYYY-MM-DD so it's easy to query
    xp_earned: int = 0

# ==========================================
# STUDY TAB MODELS (SCREEN 6A, 6B, 7)
# ==========================================

class StudySet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    title: str
    subject: str
    card_count: int = Field(default=0)
    last_studied: Optional[datetime] = Field(default=None)
    weak_cards_count: int = Field(default=0)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="study_sets")
    flashcards: List["Flashcard"] = Relationship(back_populates="study_set", cascade_delete=True)
    feynman_sessions: List["FeynmanSession"] = Relationship(back_populates="study_set", cascade_delete=True)

class Flashcard(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    study_set_id: int = Field(foreign_key="studyset.id")
    
    question: str = Field(max_length=200)
    answer: str = Field(max_length=400)
    subject: str
    difficulty: DifficultyLevel = Field(default=DifficultyLevel.medium)
    is_weak: bool = Field(default=False)

    # Relationships
    study_set: Optional["StudySet"] = Relationship(back_populates="flashcards")
    feynman_sessions: List["FeynmanSession"] = Relationship(back_populates="flashcard")

class FeynmanSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    study_set_id: int = Field(foreign_key="studyset.id")
    card_id: int = Field(foreign_key="flashcard.id")
    
    # State tracking
    comprehension_score: int = Field(default=0, ge=0, le=100)
    is_complete: bool = Field(default=False)
    
    # Storing the AI's structural outputs as JSON strings 
    gaps_identified: str = Field(default="[]") 
    strong_points: str = Field(default="[]")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    study_set: Optional["StudySet"] = Relationship(back_populates="feynman_sessions")
    flashcard: Optional["Flashcard"] = Relationship(back_populates="feynman_sessions")