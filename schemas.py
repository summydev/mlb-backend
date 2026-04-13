# schemas.py
from pydantic import BaseModel, EmailStr, Field
 
from typing import Literal
 
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
# schemas.py
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

# schemas.py

class TokenRefreshRequest(BaseModel):
    refresh_token: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=8, max_length=72)