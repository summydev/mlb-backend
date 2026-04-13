# main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status, Depends
from sqlmodel import Session, select
from database import create_db_and_tables, get_session, engine
from models import User
from schemas import UserRegister, UserLogin, TokenResponse
 
from security import (
    get_password_hash, 
    verify_password, 
    create_access_token, 
    create_refresh_token,
    get_current_user,
    create_password_reset_token,
    SECRET_KEY,      # <-- ADD THIS
    ALGORITHM        # <-- ADD THIS
)
from schemas import UserProfileUpdate
from security import get_current_user
 
from models import Pet
from schemas import PetAdoptionRequest
from pydantic import BaseModel
 # main.py
from schemas import TokenRefreshRequest, ForgotPasswordRequest, ResetPasswordRequest
from security import create_password_reset_token
from jose import jwt, JWTError
# This ensures the database tables are created when the app starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="myLB Auth API", version="1.0", lifespan=lifespan)

@app.post("/auth/register", status_code=status.HTTP_200_OK)
async def register_user(user_data: UserRegister, session: Session = Depends(get_session)):
    email = user_data.email.lower()
    
    # 1. Check if email already exists
    statement = select(User).where(User.email == email)
    existing_user = session.exec(statement).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Log in instead?"
        )
    
    # 2. Create new user
    hashed_password = get_password_hash(user_data.password)
    new_user = User(
        name=user_data.name,
        email=email,
        hashed_password=hashed_password,
        is_verified=False  # <-- Make sure this is False again!
    )
    
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    
    # 3. Generate the mock verification link
    # We use a hardcoded token for now to match our /auth/verify-email endpoint
    verification_link = f"https://mlb-backend-9jmu.onrender.com/auth/verify-email?token=mock-magic-link-token"
    
    # 4. Print the "email" to the Render logs
    print("\n" + "="*50)
    print(f"📧 MOCK EMAIL SENT TO: {email}")
    print(f"🔗 CLICK HERE TO VERIFY: {verification_link}")
    print("="*50 + "\n")
    
    return {
        "message": "Verify your email",
        "user_id": new_user.id
    }
@app.get("/auth/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(token: str, session: Session = Depends(get_session)):
    """
    This endpoint catches the magic link.
    For our mock testing, it just finds the most recently created 
    unverified user and flips them to verified!
    """
    if token != "mock-magic-link-token":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification token."
        )
    
    # Find the most recent unverified user in the database
    statement = select(User).where(User.is_verified == False).order_by(User.id.desc())
    user_to_verify = session.exec(statement).first()
    
    if not user_to_verify:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending accounts found to verify."
        )
        
    # Flip the switch!
    user_to_verify.is_verified = True
    session.add(user_to_verify)
    session.commit()
    
    return {
        "message": "Account verified successfully! You can now return to the app and log in."
    }

@app.post("/auth/login", response_model=TokenResponse)
async def login_user(credentials: UserLogin, session: Session = Depends(get_session)):
    email = credentials.email.lower()
    
    # 1. Fetch user from database
    statement = select(User).where(User.email == email)
    db_user = session.exec(statement).first()
    
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password. Please try again."
        )

    # 2. Verify password
    if not verify_password(credentials.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password. Please try again."
        )

    # 3. Check verification status
    if not db_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email first."
        )

    # 4. Generate Tokens
    access_token = create_access_token(data={"sub": db_user.email})
    refresh_token = create_refresh_token(data={"sub": db_user.email})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": db_user.id,
            "email": db_user.email,
            "name": db_user.name
        }
    }


@app.patch("/users/me/profile", status_code=status.HTTP_200_OK)
async def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user), # <-- THE MAGIC LOCK 🔒
    session: Session = Depends(get_session)
):
    # Update the user's data
    current_user.study_goal = profile_data.study_goal
    
    # Save to database
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    
    return {
        "message": "Profile updated successfully",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name,
            "study_goal": current_user.study_goal
        }
    }



@app.post("/users/me/pet", status_code=status.HTTP_200_OK)
async def adopt_pet(
    pet_data: PetAdoptionRequest,
    current_user: User = Depends(get_current_user), # 🔒 Requires valid JWT
    session: Session = Depends(get_session)
):
    # 1. Check if the user already has a pet (Optional, but safe!)
    statement = select(Pet).where(Pet.user_id == current_user.id)
    existing_pet = session.exec(statement).first()
    
    if existing_pet:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already adopted a buddy!"
        )

    # 2. Trim whitespace from the name just like the spec requested
    clean_pet_name = pet_data.pet_name.strip()

    # 3. Create the new pet in the database
    new_pet = Pet(
        user_id=current_user.id,
        pet_type=pet_data.pet_type,
        pet_name=clean_pet_name
    )
    
    session.add(new_pet)
    session.commit()
    session.refresh(new_pet)
    
    # 4. Return the exact response specified in the developer handoff
    return {
        "pet_id": new_pet.id,
        "pet_type": new_pet.pet_type,
        "pet_name": new_pet.pet_name,
        "level": new_pet.level,
        "xp": new_pet.xp
    }
# main.py

@app.get("/users/me/dashboard", status_code=status.HTTP_200_OK)
async def get_dashboard(
    current_user: User = Depends(get_current_user), # 🔒 Requires valid JWT
    session: Session = Depends(get_session)
):
    # 1. Fetch the user's pet from the database
    statement = select(Pet).where(Pet.user_id == current_user.id)
    pet = session.exec(statement).first()
    
    # Format the pet data (if they have one)
    pet_data = None
    if pet:
        pet_data = {
            "pet_id": pet.id,
            "pet_type": pet.pet_type,
            "pet_name": pet.pet_name,
            "level": pet.level,
            "xp": pet.xp
        }

    # 2. Return the exact payload the Handoff Document requires
    return {
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "study_goal": current_user.study_goal,
            "is_first_session": current_user.is_first_session
        },
        "pet": pet_data,
        "quests": [],      # Empty list triggers "Join a study group..." UI
        "today_plan": [],  # Empty list triggers "No plan yet..." UI
        "streak": 0        # New users start at 0
    }
 

class FirstSessionUpdate(BaseModel):
    is_first_session: bool

@app.patch("/users/me", status_code=status.HTTP_200_OK)
async def complete_tooltip_tour(
    update_data: FirstSessionUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    current_user.is_first_session = update_data.is_first_session
    
    session.add(current_user)
    session.commit()
    
    return {"message": "User session status updated successfully."}


# ---------------------------------------------------------
# 1. SILENT TOKEN REFRESH
# ---------------------------------------------------------
@app.post("/auth/token/refresh", response_model=TokenResponse)
async def refresh_access_token(request: TokenRefreshRequest, session: Session = Depends(get_session)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or refresh token expired."
    )
    try:
        # Decode the refresh token
        payload = jwt.decode(request.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    # Check if user still exists in the DB
    statement = select(User).where(User.email == email)
    db_user = session.exec(statement).first()
    if not db_user:
        raise credentials_exception

    # Generate a fresh set of tokens
    new_access_token = create_access_token(data={"sub": db_user.email})
    new_refresh_token = create_refresh_token(data={"sub": db_user.email})
    
    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "user": {
            "id": db_user.id,
            "email": db_user.email,
            "name": db_user.name
        }
    }

# ---------------------------------------------------------
# 2. FORGOT PASSWORD (Mock Email)
# ---------------------------------------------------------
@app.post("/auth/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(request: ForgotPasswordRequest, session: Session = Depends(get_session)):
    email = request.email.lower()
    
    statement = select(User).where(User.email == email)
    db_user = session.exec(statement).first()
    
    # If the user exists, generate the token and print the mock email
    if db_user:
        reset_token = create_password_reset_token(email)
        reset_link = f"myLB://reset-password?token={reset_token}" # Using the deep link from the spec
        
        print("\n" + "="*50)
        print(f"🔐 PASSWORD RESET REQUESTED FOR: {email}")
        print(f"🔗 MOCK DEEP LINK: {reset_link}")
        print("="*50 + "\n")

    # ALWAYS return this exact message to prevent user enumeration
    return {
        "message": "If an account with that email exists, you'll receive a reset link."
    }

# ---------------------------------------------------------
# 3. RESET PASSWORD
# ---------------------------------------------------------
@app.post("/auth/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(request: ResetPasswordRequest, session: Session = Depends(get_session)):
    invalid_token_exception = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired reset token."
    )
    
    try:
        # Decode the reset token
        payload = jwt.decode(request.token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        # Ensure it's actually a reset token, not an access token
        if email is None or token_type != "password_reset":
            raise invalid_token_exception
    except JWTError:
        raise invalid_token_exception
        
    # Find the user
    statement = select(User).where(User.email == email)
    db_user = session.exec(statement).first()
    
    if not db_user:
        raise invalid_token_exception
        
    # Hash the new password and save it
    db_user.hashed_password = get_password_hash(request.password)
    session.add(db_user)
    session.commit()
    
    return {"message": "Password updated successfully. Please log in."}