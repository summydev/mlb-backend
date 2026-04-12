# models.py
from sqlmodel import SQLModel, Field

# table=True tells SQLModel to create a real database table for this!
class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=2, max_length=60)
    email: str = Field(unique=True, index=True) # index=True makes logins incredibly fast
    hashed_password: str
    is_verified: bool = Field(default=False)