from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, status, Depends
from sqlmodel import Session, select
from jose import jwt, JWTError

# Assuming these exist based on your previous snippets
from database import create_db_and_tables, get_session, engine
from models import User, Pet,StudyPlan, StudySession, DailyActivity
from security import (
    get_password_hash, 
    verify_password, 
    create_access_token, 
    create_refresh_token,
    get_current_user,
    create_password_reset_token,
    SECRET_KEY,      
    ALGORITHM        
)
from schemas import (
    UserRegister, UserLogin, TokenResponse, UserProfileUpdate, PetAdoptionRequest,
    TokenRefreshRequest, ForgotPasswordRequest, ResetPasswordRequest, FirstSessionUpdate,
    DashboardResponse, UserDashboardInfo, PetDashboardInfo, StreakInfo,
    PlanResponse, PlanGenerateRequest, SessionUpdateRequest, PlanApproveRequest,
    SolveRequest, SolveResponse, SolveFeedbackRequest, PlanGoal
)
from ai_service import generate_deepseek_solution, generate_deepseek_study_plan
from models import StudyPlan, StudySession
import uuid
from typing import Optional, List

# This ensures the database tables are created when the app starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="myLB Auth API", version="1.0", lifespan=lifespan)

# ==========================================
# AUTHENTICATION ROUTES
# ==========================================

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
        is_verified=False  # Must be verified before login
    )
    
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    
    # 3. Generate the mock verification link
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

@app.post("/auth/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(request: ForgotPasswordRequest, session: Session = Depends(get_session)):
    email = request.email.lower()
    
    statement = select(User).where(User.email == email)
    db_user = session.exec(statement).first()
    
    # If the user exists, generate the token and print the mock email
    if db_user:
        reset_token = create_password_reset_token(email)
        reset_link = f"myLB://reset-password?token={reset_token}" 
        
        print("\n" + "="*50)
        print(f"🔐 PASSWORD RESET REQUESTED FOR: {email}")
        print(f"🔗 MOCK DEEP LINK: {reset_link}")
        print("="*50 + "\n")

    # ALWAYS return this exact message to prevent user enumeration
    return {
        "message": "If an account with that email exists, you'll receive a reset link."
    }

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


# ==========================================
# PROTECTED ONBOARDING ROUTES
# ==========================================

@app.patch("/users/me/profile", status_code=status.HTTP_200_OK)
async def update_user_profile(
    profile_data: UserProfileUpdate,
    current_user: User = Depends(get_current_user), # 🔒 Requires valid JWT
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
    # 1. Check if the user already has a pet
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

@app.patch("/users/me", status_code=status.HTTP_200_OK)
async def complete_tooltip_tour(
    update_data: FirstSessionUpdate,
    current_user: User = Depends(get_current_user), # 🔒 Requires valid JWT
    session: Session = Depends(get_session)
):
    current_user.is_first_session = update_data.is_first_session
    
    session.add(current_user)
    session.commit()
    
    return {"message": "User session status updated successfully."}


# ==========================================
# MAIN DASHBOARD (HOME TAB)
# ==========================================

@app.get("/users/me/dashboard", response_model=DashboardResponse, status_code=status.HTTP_200_OK)
async def get_dashboard(
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    
    # 1. Calculate dynamic greeting based on server time 
    current_hour = datetime.now().hour
    if current_hour < 12:
        greeting = "Good morning"
    elif current_hour < 18:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    first_name = current_user.name.split()[0] if current_user.name else "Student"

    user_info = UserDashboardInfo(
        first_name=first_name, 
        is_first_session=current_user.is_first_session 
    )

    # 2. Calculate the Real XP History for the last 7 days
    today = datetime.now().date()
    # Generate a list of strings for the last 7 days: ['2026-04-09', '2026-04-10', ..., '2026-04-15']
    last_7_days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    
    # Query the database for any activity on these specific dates
    statement = select(DailyActivity).where(
        DailyActivity.user_id == current_user.id,
        DailyActivity.date.in_(last_7_days)
    )
    activities = session.exec(statement).all()
    
    # Map the results: { "2026-04-14": 150, "2026-04-15": 200 }
    xp_map = {activity.date: activity.xp_earned for activity in activities}
    
    # Build the final array, defaulting to 0 if they didn't study that day
    real_xp_history = [xp_map.get(day, 0) for day in last_7_days]

    # 3. Fetch actual Pet Data from the database
    statement = select(Pet).where(Pet.user_id == current_user.id)
    pet = session.exec(statement).first()
    
    if pet:
        pet_info = PetDashboardInfo(
            name=pet.pet_name, 
            type=pet.pet_type, 
            level=pet.level, 
            xp=pet.xp, 
            xp_to_next=1200, 
            mood="happy",
            xp_history=real_xp_history # <-- Real database data!
        )
    else:
        pet_info = PetDashboardInfo(
            name="Nova", type="nova", level=1, xp=0, xp_to_next=1200, mood="happy",
            xp_history=[0, 0, 0, 0, 0, 0, 0] 
        )

    streak_info = StreakInfo(days=0, active_today=False)

    return DashboardResponse(
        user=user_info,
        pet=pet_info,
        quests=[], 
        today_plan=[], 
        streak=streak_info,
        greeting=greeting
    )

# ==========================================
# STUDY PLAN ROUTES (SCREEN 9)
# ==========================================

@app.get("/users/me/plan", response_model=Optional[PlanResponse], status_code=status.HTTP_200_OK)
async def get_study_plan(
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    # TODO: Fetch the active plan from the database.
    # Returning None for now to trigger the Flutter UI's "Empty State / Goal Setup" modal.
    return None




@app.post("/users/me/plan/generate", response_model=PlanResponse, status_code=status.HTTP_200_OK)
async def generate_study_plan(
    request: PlanGenerateRequest,
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    # 1. Calculate days remaining
    today = datetime.now().date()
    days_remaining = (request.deadline - today).days
    
    if days_remaining < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your deadline has already passed. Please choose a future date."
        )

    # 2. Call DeepSeek
    ai_plan_data = await generate_deepseek_study_plan(
        goal=request.goal, 
        target_date=request.deadline, 
        days_remaining=days_remaining
    )

    if not ai_plan_data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate your study plan. Please try again."
        )

    # 3. Create the Database Record for the Plan
    db_plan = StudyPlan(
        user_id=current_user.id,
        subject=request.goal,
        deadline=request.deadline,
        is_approved=False
    )
    session.add(db_plan)
    session.commit()
    session.refresh(db_plan)

    # 4. Create the Database Records for the Sessions
    db_sessions = []
    for ai_session in ai_plan_data.get("sessions", []):
        db_session = StudySession(
            plan_id=db_plan.id,
            user_id=current_user.id,
            date=ai_session["date"],
            time=ai_session.get("time", "12:00"), # Default time if AI misses it
            subject=ai_session["subject"],
            duration_mins=ai_session["duration_mins"],
            mode=ai_session["mode"],
            priority=ai_session["priority"]
        )
        session.add(db_session)
        db_sessions.append(db_session)
        
        # Add a unique ID to the returned dictionary for the Flutter app
        ai_session["id"] = f"ses_{uuid.uuid4().hex[:8]}"
        ai_session["completed"] = False
        
    session.commit()

    # 5. Construct the final response matching the PlanResponse schema
    return PlanResponse(
        goal=PlanGoal(subject=request.goal, deadline=request.deadline),
        stats=ai_plan_data["stats"],
        week=ai_plan_data["week"],
        sessions=ai_plan_data["sessions"],
        nudge=None # Optional AI nudges can be built later
    )

@app.patch("/users/me/plan/session/{session_id}", status_code=status.HTTP_200_OK)
async def update_session(
    session_id: str,
    request: SessionUpdateRequest,
    current_user: User = Depends(get_current_user), 
    db_session: Session = Depends(get_session)
):
    # TODO: Find session by ID and update time, duration, or mark as skipped.
    return {"message": f"Session {session_id} updated successfully"}


@app.patch("/users/me/plan", status_code=status.HTTP_200_OK)
async def approve_study_plan(
    request: PlanApproveRequest,
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    # TODO: Mark the user's active plan as approved = true in the database.
    return {"message": "Plan approved successfully"}

@app.post("/solve", response_model=SolveResponse, status_code=status.HTTP_200_OK)
async def solve_question(
    request: SolveRequest,
    current_user: User = Depends(get_current_user)
):
    # For now, we are handling text input. We will handle image_base64 later.
    if not request.question_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a question_text."
        )

    # Call our new DeepSeek service
    solution_data = await generate_deepseek_solution(request.question_text)

    if not solution_data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Couldn't generate a solution. Try again." # Matches the spec error state [cite: 185]
        )

    # Return the validated payload
    return SolveResponse(**solution_data)

@app.post("/solve/{solution_id}/feedback", status_code=status.HTTP_200_OK)
async def submit_solution_feedback(
    solution_id: str,
    request: SolveFeedbackRequest,
    current_user: User = Depends(get_current_user)
):
    # TODO: In the future, save this feedback to a database table to fine-tune your AI.
    
    # For now, print to logs so you can see it working
    print(f"Feedback for {solution_id}: Helpful? {request.helpful}. Reason: {request.flag_reason}")
    
    return {"acknowledged": True} # Spec dictates returning this exactly
# ==========================================
# STUDY PLAN ADJUSTMENTS (SCREEN 9)
# ==========================================

@app.patch("/users/me/plan/session/{session_id}", status_code=status.HTTP_200_OK)
async def update_session(
    session_id: int, # Matches the integer ID in our database
    request: SessionUpdateRequest,
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    # 1. Find the specific session, ensuring it belongs to the current user
    statement = select(StudySession).where(
        StudySession.id == session_id,
        StudySession.user_id == current_user.id
    )
    db_session = session.exec(statement).first()
    
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found."
        )

    # 2. Update only the fields the Flutter app sent us
    if request.scheduled_time is not None:
        db_session.time = request.scheduled_time
    if request.duration_mins is not None:
        db_session.duration_mins = request.duration_mins
    if request.skipped is not None:
        db_session.skipped = request.skipped

    # 3. Save changes
    session.add(db_session)
    session.commit()
    session.refresh(db_session)
    
    return db_session


@app.patch("/users/me/plan", status_code=status.HTTP_200_OK)
async def approve_study_plan(
    request: PlanApproveRequest,
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    # 1. Find the user's most recently generated (but unapproved) plan
    statement = select(StudyPlan).where(
        StudyPlan.user_id == current_user.id,
        StudyPlan.is_approved == False
    ).order_by(StudyPlan.id.desc())
    
    db_plan = session.exec(statement).first()
    
    if not db_plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending plan found to approve."
        )
        
    # 2. Mark it as approved
    db_plan.is_approved = request.approved
    session.add(db_plan)
    session.commit()
    
    return {"message": "Plan approved successfully"}