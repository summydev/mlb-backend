import uuid
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

class CanvasSourceType(str, Enum):
    notes = "notes"
    upload = "upload"
    manual = "manual"

class NodeSize(str, Enum):
    small = "small"
    medium = "medium"
    large = "large"

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
    fcm_token: Optional[str] = Field(default=None) # Used for Firebase Push Notifications
    
    # Relationships
    pets: List["Pet"] = Relationship(back_populates="user")
    quests: List["Quest"] = Relationship(back_populates="user")
    study_plans: List["StudyPlan"] = Relationship(back_populates="user")
    study_sets: List["StudySet"] = Relationship(back_populates="user")
    notes: List["Note"] = Relationship(back_populates="user")
    canvases: List["Canvas"] = Relationship(back_populates="user")

class Pet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    pet_type: str
    pet_name: str
    level: int = 1
    xp: int = 0
    
    # Relationships
    user: Optional["User"] = Relationship(back_populates="pets")

# ==========================================
# DASHBOARD & STUDY PLAN MODELS
# ==========================================

class Quest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    title: str
    type: str # "coop" or "solo"
    progress: int = 0
    target: int
    members_count: Optional[int] = None
    
    # Relationships
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
    
    date: str # Stored as a string YYYY-MM-DD
    time: Optional[str] = None # e.g., "14:00"
    subject: str
    duration_mins: int
    mode: str # "flashcard", "feynman", "review"
    priority: str # "normal", "high", "weak_area"
    completed: bool = False
    skipped: bool = False
    
    # Relationships
    plan: Optional["StudyPlan"] = Relationship(back_populates="sessions")

class DailyActivity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    date: str # Stored as YYYY-MM-DD
    xp_earned: int = 0

# ==========================================
# STUDY TAB & NOTES MODELS
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
    note_id: Optional[int] = Field(default=None, foreign_key="note.id")
    
    question: str = Field(max_length=200)
    answer: str = Field(max_length=400)
    subject: str
    difficulty: DifficultyLevel = Field(default=DifficultyLevel.medium)
    is_weak: bool = Field(default=False)

    # Relationships
    study_set: Optional["StudySet"] = Relationship(back_populates="flashcards")
    note: Optional["Note"] = Relationship(back_populates="flashcards")
    feynman_sessions: List["FeynmanSession"] = Relationship(back_populates="flashcard")
    canvas_nodes: List["CanvasNode"] = Relationship(back_populates="flashcard")

class FeynmanSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    study_set_id: int = Field(foreign_key="studyset.id")
    card_id: int = Field(foreign_key="flashcard.id")
    
    comprehension_score: int = Field(default=0, ge=0, le=100)
    is_complete: bool = Field(default=False)
    
    gaps_identified: str = Field(default="[]") 
    strong_points: str = Field(default="[]")
    
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    study_set: Optional["StudySet"] = Relationship(back_populates="feynman_sessions")
    flashcard: Optional["Flashcard"] = Relationship(back_populates="feynman_sessions")

class Note(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    title: str = Field(default="Untitled note", max_length=60)
    subject: str
    content_text: str = Field(default="")
    content_html: Optional[str] = Field(default=None)
    
    word_count: int = Field(default=0)
    card_count: int = Field(default=0)
    weak_card_count: int = Field(default=0)
    has_canvas: bool = Field(default=False)
    snippet: str = Field(default="", max_length=80)
    is_public: bool = Field(default=False)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    user: Optional["User"] = Relationship(back_populates="notes")
    flashcards: List["Flashcard"] = Relationship(back_populates="note", cascade_delete=True)
    canvases: List["Canvas"] = Relationship(back_populates="note")

# ==========================================
# CANVAS MODELS (INFINITE CANVAS TAB)
# ==========================================

class Canvas(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    
    name: str
    subject: str
    node_count: int = Field(default=0)
    weak_node_count: int = Field(default=0)
    thumbnail_url: Optional[str] = Field(default=None)
    
    source_type: CanvasSourceType = Field(default=CanvasSourceType.manual)
    source_id: Optional[int] = Field(default=None, foreign_key="note.id")
    
    last_studied_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_public: bool = Field(default=False)
    
    # Relationships
    user: Optional["User"] = Relationship(back_populates="canvases")
    note: Optional["Note"] = Relationship(back_populates="canvases")
    nodes: List["CanvasNode"] = Relationship(back_populates="canvas", cascade_delete=True)
    connections: List["CanvasConnection"] = Relationship(back_populates="canvas", cascade_delete=True)

class CanvasNode(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    canvas_id: uuid.UUID = Field(foreign_key="canvas.id")
    
    label: str = Field(max_length=40)
    x: float
    y: float
    size: NodeSize = Field(default=NodeSize.medium)
    is_hero: bool = Field(default=False)
    is_weak: bool = Field(default=False)
    definition: Optional[str] = Field(default=None)
    
    card_id: Optional[int] = Field(default=None, foreign_key="flashcard.id")
    
    # Relationships
    canvas: Optional["Canvas"] = Relationship(back_populates="nodes")
    flashcard: Optional["Flashcard"] = Relationship(back_populates="canvas_nodes")
    
    outgoing_connections: List["CanvasConnection"] = Relationship(
        back_populates="from_node",
        sa_relationship_kwargs={"foreign_keys": "[CanvasConnection.from_node_id]", "cascade": "all, delete-orphan"}
    )
    incoming_connections: List["CanvasConnection"] = Relationship(
        back_populates="to_node",
        sa_relationship_kwargs={"foreign_keys": "[CanvasConnection.to_node_id]", "cascade": "all, delete-orphan"}
    )

class CanvasConnection(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    canvas_id: uuid.UUID = Field(foreign_key="canvas.id")
    from_node_id: uuid.UUID = Field(foreign_key="canvasnode.id")
    to_node_id: uuid.UUID = Field(foreign_key="canvasnode.id")
    
    label: Optional[str] = Field(default=None)
    
    # Relationships
    canvas: Optional["Canvas"] = Relationship(back_populates="connections")
    from_node: Optional["CanvasNode"] = Relationship(
        back_populates="outgoing_connections",
        sa_relationship_kwargs={"foreign_keys": "[CanvasConnection.from_node_id]"}
    )
    to_node: Optional["CanvasNode"] = Relationship(
        back_populates="incoming_connections",
        sa_relationship_kwargs={"foreign_keys": "[CanvasConnection.to_node_id]"}
    )

# ==========================================
# COLLECTIONS MODELS
# ==========================================

class Collection(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id") # The Owner
    
    title: str
    description: Optional[str] = None
    subject: str
    cover_emoji: Optional[str] = None
    
    visibility: str = Field(default="private") # "private", "shared", "public"
    share_token: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], unique=True)
    save_count: int = Field(default=0)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class CollectionItem(SQLModel, table=True):
    """Mapping table linking a Collection to Notes, Sets, or Canvases"""
    id: Optional[int] = Field(default=None, primary_key=True)
    collection_id: int = Field(foreign_key="collection.id")
    
    item_type: str # "note", "set", "canvas"
    item_id: str 
    position: int = Field(default=0) # For drag-and-drop reordering

class CollectionAccess(SQLModel, table=True):
    """For the 'Shared' and 'Private' visibility tiers"""
    id: Optional[int] = Field(default=None, primary_key=True)
    collection_id: int = Field(foreign_key="collection.id")
    user_id: int = Field(foreign_key="user.id") # The user who is granted access
    granted_at: datetime = Field(default_factory=datetime.utcnow)

class CollectionRequest(SQLModel, table=True):
    """For Pending Access Requests"""
    id: Optional[int] = Field(default=None, primary_key=True)
    collection_id: int = Field(foreign_key="collection.id")
    user_id: int = Field(foreign_key="user.id") # The user requesting access
    message: Optional[str] = None
    status: str = Field(default="pending") # "pending", "approved", "denied"
    requested_at: datetime = Field(default_factory=datetime.utcnow)

class Notification(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id") # The person receiving the notification
    
    title: str
    body: str
    deep_link: Optional[str] = None # e.g., "/collections/12/share"
    is_read: bool = Field(default=False)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)