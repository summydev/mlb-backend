# models.py
from sqlmodel import SQLModel, Field

class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=2, max_length=60)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    is_verified: bool = Field(default=False)
    # NEW: Add the study_goal field
    study_goal: str | None = Field(default=None)
    is_first_session: bool = Field(default=True)

# models.py
# (Make sure to keep your User model exactly as it is)

class Pet(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True) # Ensures 1 user = 1 pet
    pet_type: str
    pet_name: str
    level: int = Field(default=1) # Starts at level 1
    xp: int = Field(default=0)    # Starts with 0 XP