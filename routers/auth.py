from fastapi import APIRouter, HTTPException, status, Depends, Request
from sqlmodel import Session, select
from jose import jwt, JWTError
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
import os
import resend

# Database and Models
from database import get_session
from models import User

# Security
from security import (
    get_password_hash, verify_password, create_access_token, create_refresh_token,
    get_current_user, create_password_reset_token, SECRET_KEY, ALGORITHM
)

# Schemas
from schemas import (
    UserRegister, UserLogin, TokenResponse, 
    TokenRefreshRequest, ForgotPasswordRequest, ResetPasswordRequest
)

limiter = Limiter(key_func=get_remote_address)

resend.api_key = os.getenv("RESEND_API_KEY")
FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev") 

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class LogoutRequest(BaseModel):
    refresh_token: str

router = APIRouter(prefix="/auth", tags=["Authentication"])

def send_email(to_email: str, subject: str, html_content: str):
    try:
        r = resend.Emails.send({
            "from": f"myLB <{FROM_EMAIL}>",
            "to": [to_email],
            "subject": subject,
            "html": html_content
        })
        return True
    except Exception as e:
        print(f"❌ Failed to send email to {to_email}: {e}")
        return False

# FIXED: Returns TokenResponse directly so user is instantly logged in
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
def register_user(request: Request, user_data: UserRegister, session: Session = Depends(get_session)):
    email = user_data.email.lower()
    statement = select(User).where(User.email == email)
    existing_user = session.exec(statement).first()
    
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        name=user_data.name, 
        email=email, 
        hashed_password=hashed_password, 
        is_verified=True,
        is_first_session=True, # Flag as new user for onboarding
        token_version=1
    )
    
    session.add(new_user)
    session.commit()
    session.refresh(new_user)

    access_token = create_access_token(data={"sub": new_user.email}, version=new_user.token_version)
    refresh_token = create_refresh_token(data={"sub": new_user.email}, version=new_user.token_version)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": new_user.id,
            "email": new_user.email,
            "name": new_user.name,
            "is_first_session": new_user.is_first_session
        }
    }

# FIXED: Includes is_first_session in user payload
@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login_user(request: Request, credentials: UserLogin, session: Session = Depends(get_session)):
    email = credentials.email.lower()
    statement = select(User).where(User.email == email)
    db_user = session.exec(statement).first()
    
    if not db_user or not verify_password(credentials.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")

    access_token = create_access_token(data={"sub": db_user.email}, version=db_user.token_version)
    refresh_token = create_refresh_token(data={"sub": db_user.email}, version=db_user.token_version)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": db_user.id,
            "email": db_user.email,
            "name": db_user.name,
            "is_first_session": db_user.is_first_session
        }
    }

# FIXED: Includes is_first_session in token refresh
@router.post("/token/refresh", response_model=TokenResponse)
def refresh_access_token(request: TokenRefreshRequest, session: Session = Depends(get_session)):
    try:
        payload = jwt.decode(request.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        token_version: int = payload.get("version")
        if email is None or token_version is None: raise JWTError
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
        
    db_user = session.exec(select(User).where(User.email == email)).first()
    if not db_user: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    
    if db_user.token_version != token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please log in again.")

    return {
        "access_token": create_access_token(data={"sub": db_user.email}, version=db_user.token_version),
        "refresh_token": create_refresh_token(data={"sub": db_user.email}, version=db_user.token_version),
        "token_type": "bearer",
        "user": {
            "id": db_user.id,
            "email": db_user.email,
            "name": db_user.name,
            "is_first_session": db_user.is_first_session
        }
    }

@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
def forgot_password(request: Request, body: ForgotPasswordRequest, session: Session = Depends(get_session)):
    db_user = session.exec(select(User).where(User.email == body.email.lower())).first()
    if db_user:
        reset_link = f"mylb://reset-password?token={create_password_reset_token(db_user.email, db_user.token_version)}" 
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; text-align: center;">
            <h2 style="color: #2196F3;">Password Reset Request</h2>
            <p>Hi {db_user.name.split()[0]},</p>
            <p>Click below to reset your password:</p>
            <a href="{reset_link}" style="display: inline-block; padding: 12px 24px; margin: 20px 0; background-color: #2196F3; color: white; text-decoration: none; border-radius: 8px; font-weight: bold;">Reset Password</a>
        </div>
        """
        send_email(db_user.email, "Reset your myLB Password", html_content)
        
    return {"message": "If an account with that email exists, you'll receive a reset link."}

@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(request: ResetPasswordRequest, session: Session = Depends(get_session)):
    try:
        payload = jwt.decode(request.token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "password_reset": raise JWTError
        db_user = session.exec(select(User).where(User.email == payload.get("sub"))).first()
        if not db_user or db_user.token_version != payload.get("version"): 
            raise JWTError
    except JWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token.")
        
    db_user.hashed_password = get_password_hash(request.password)
    db_user.token_version += 1
    session.add(db_user)
    session.commit()
    return {"message": "Password updated successfully."}

@router.post("/change-password", status_code=status.HTTP_200_OK)
def change_password(request: ChangePasswordRequest, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect current password")
        
    current_user.hashed_password = get_password_hash(request.new_password)
    current_user.token_version += 1
    session.add(current_user)
    session.commit()
    return {"success": True, "message": "Password updated successfully. You will be logged out of other devices."}

@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(request: LogoutRequest, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    current_user.token_version += 1
    session.add(current_user)
    session.commit()
    return {"logged_out": True, "message": "Successfully logged out securely."}