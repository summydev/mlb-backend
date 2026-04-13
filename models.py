from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import date

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

class Pet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    pet_type: str
    pet_name: str
    level: int = 1
    xp: int = 0
    
    # Relationship back to the User
    user: Optional[User] = Relationship(back_populates="pets")


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
    user: Optional[User] = Relationship(back_populates="quests")

class StudyPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    subject: str
    deadline: date
    is_approved: bool = False
    
    # Relationships
    user: Optional[User] = Relationship(back_populates="study_plans")
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
    plan: Optional[StudyPlan] = Relationship(back_populates="sessions")