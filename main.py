from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from jose import jwt, JWTError
import uuid
from typing import Optional, List

# Database and Models
from database import create_db_and_tables, get_session, engine
from models import User, Pet, StudyPlan, StudySession, DailyActivity, Quest # <-- Added Quest

# Security
from security import (
    get_password_hash, verify_password, create_access_token, create_refresh_token,
    get_current_user, create_password_reset_token, SECRET_KEY, ALGORITHM
)

# Schemas
from schemas import (
    UserRegister, UserLogin, TokenResponse, UserProfileUpdate, PetAdoptionRequest,
    TokenRefreshRequest, ForgotPasswordRequest, ResetPasswordRequest, FirstSessionUpdate,
    DashboardResponse, UserDashboardInfo, PetDashboardInfo, StreakInfo,
    PlanResponse, PlanGenerateRequest, SessionUpdateRequest, PlanApproveRequest,
    SolveRequest, SolveResponse, SolveFeedbackRequest, PlanGoal, TodayPlanSession,
     PlanStats, WeekDay, SessionDetail # <-- Added TodayPlanSession
)

# AI Service
from ai_service import generate_deepseek_solution, generate_deepseek_study_plan
from routers import study

# ... your other app setup ...


# This ensures the database tables are created when the app starts
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="myLB Auth API", version="1.0", lifespan=lifespan)

app.include_router(study.router)
# Allow Flutter app to communicate with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================
# AUTHENTICATION ROUTES
# ==========================================

@app.post("/auth/register", status_code=status.HTTP_200_OK)
async def register_user(user_data: UserRegister, session: Session = Depends(get_session)):
    email = user_data.email.lower()
    statement = select(User).where(User.email == email)
    existing_user = session.exec(statement).first()
    
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists.")
    
    hashed_password = get_password_hash(user_data.password)
    new_user = User(name=user_data.name, email=email, hashed_password=hashed_password, is_verified=False)
    
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    
    verification_link = f"https://mlb-backend-9jmu.onrender.com/auth/verify-email?token=mock-magic-link-token"
    print("\n" + "="*50)
    print(f"📧 MOCK EMAIL SENT TO: {email}")
    print(f"🔗 CLICK HERE TO VERIFY: {verification_link}")
    print("="*50 + "\n")
    
    return {"message": "Verify your email", "user_id": new_user.id}

@app.get("/auth/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(token: str, session: Session = Depends(get_session)):
    if token != "mock-magic-link-token":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
    
    statement = select(User).where(User.is_verified == False).order_by(User.id.desc())
    user_to_verify = session.exec(statement).first()
    
    if not user_to_verify:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No pending accounts found.")
        
    user_to_verify.is_verified = True
    session.add(user_to_verify)
    session.commit()
    return {"message": "Account verified successfully! You can now log in."}

@app.post("/auth/login", response_model=TokenResponse)
async def login_user(credentials: UserLogin, session: Session = Depends(get_session)):
    email = credentials.email.lower()
    statement = select(User).where(User.email == email)
    db_user = session.exec(statement).first()
    
    if not db_user or not verify_password(credentials.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password.")

    if not db_user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Please verify your email first.")

    access_token = create_access_token(data={"sub": db_user.email})
    refresh_token = create_refresh_token(data={"sub": db_user.email})
    
    return {
        "access_token": access_token, "refresh_token": refresh_token,
        "user": {"id": db_user.id, "email": db_user.email, "name": db_user.name}
    }

@app.post("/auth/token/refresh", response_model=TokenResponse)
async def refresh_access_token(request: TokenRefreshRequest, session: Session = Depends(get_session)):
    try:
        payload = jwt.decode(request.refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None: raise JWTError
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
        
    db_user = session.exec(select(User).where(User.email == email)).first()
    if not db_user: raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    return {
        "access_token": create_access_token(data={"sub": db_user.email}),
        "refresh_token": create_refresh_token(data={"sub": db_user.email}),
        "user": {"id": db_user.id, "email": db_user.email, "name": db_user.name}
    }

@app.post("/auth/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(request: ForgotPasswordRequest, session: Session = Depends(get_session)):
    db_user = session.exec(select(User).where(User.email == request.email.lower())).first()
    if db_user:
        reset_link = f"myLB://reset-password?token={create_password_reset_token(db_user.email)}" 
        print(f"\n🔐 MOCK DEEP LINK: {reset_link}\n")
    return {"message": "If an account with that email exists, you'll receive a reset link."}

@app.post("/auth/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(request: ResetPasswordRequest, session: Session = Depends(get_session)):
    try:
        payload = jwt.decode(request.token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "password_reset": raise JWTError
        db_user = session.exec(select(User).where(User.email == payload.get("sub"))).first()
        if not db_user: raise JWTError
    except JWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token.")
        
    db_user.hashed_password = get_password_hash(request.password)
    session.add(db_user)
    session.commit()
    return {"message": "Password updated successfully."}


# ==========================================
# PROTECTED ONBOARDING ROUTES
# ==========================================

@app.patch("/users/me/profile", status_code=status.HTTP_200_OK)
async def update_user_profile(
    profile_data: UserProfileUpdate, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    current_user.study_goal = profile_data.study_goal
    session.add(current_user)
    session.commit()
    return {"message": "Profile updated successfully"}

@app.post("/users/me/pet", status_code=status.HTTP_200_OK)
async def adopt_pet(
    pet_data: PetAdoptionRequest, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    if session.exec(select(Pet).where(Pet.user_id == current_user.id)).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already adopted!")

    new_pet = Pet(user_id=current_user.id, pet_type=pet_data.pet_type, pet_name=pet_data.pet_name.strip())
    session.add(new_pet)
    session.commit()
    session.refresh(new_pet)
    return {"pet_id": new_pet.id, "pet_type": new_pet.pet_type, "pet_name": new_pet.pet_name, "level": new_pet.level, "xp": new_pet.xp}

@app.patch("/users/me", status_code=status.HTTP_200_OK)
async def complete_tooltip_tour(
    update_data: FirstSessionUpdate, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)
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
    # 1. Greeting & User Info
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    user_info = UserDashboardInfo(
        first_name=current_user.name.split()[0] if current_user.name else "Student", 
        is_first_session=current_user.is_first_session 
    )

    # 2. XP History & Streak (Real Data)
    today_str = datetime.now().date().isoformat()
    last_7_days = [(datetime.now().date() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    
    activities = session.exec(select(DailyActivity).where(
        DailyActivity.user_id == current_user.id, DailyActivity.date.in_(last_7_days)
    )).all()
    
    xp_map = {activity.date: activity.xp_earned for activity in activities}
    real_xp_history = [xp_map.get(day, 0) for day in last_7_days]
    
    # If they earned XP today, streak is active!
    streak_active = bool(xp_map.get(today_str, 0) > 0)
    streak_info = StreakInfo(days=0, active_today=streak_active)

    # 3. Pet Data
    pet = session.exec(select(Pet).where(Pet.user_id == current_user.id)).first()
    if pet:
        pet_info = PetDashboardInfo(
            name=pet.pet_name, type=pet.pet_type, level=pet.level, xp=pet.xp, 
            xp_to_next=1200, mood="happy", xp_history=real_xp_history 
        )
    else:
        pet_info = PetDashboardInfo(name="Nova", type="nova", level=1, xp=0, xp_to_next=1200, mood="happy", xp_history=[0]*7)

    # 4. Today's Plan Data (Real Data)
    today_sessions = session.exec(select(StudySession).where(
        StudySession.user_id == current_user.id, StudySession.date == today_str, StudySession.completed == False
    ).limit(4)).all()
    
    real_today_plan = [
        TodayPlanSession(id=str(s.id), subject=s.subject, duration_mins=s.duration_mins, mode=s.mode) 
        for s in today_sessions
    ]

    # 5. Active Quests (Real Data)
    db_quests = session.exec(select(Quest).where(Quest.user_id == current_user.id).limit(3)).all()
    real_quests = [
        {
            "id": str(q.id), "title": q.title, "type": q.type, 
            "progress": q.progress, "target": q.target, "members_count": q.members_count
        } for q in db_quests
    ]

    return DashboardResponse(
        user=user_info, pet=pet_info, quests=real_quests, 
        today_plan=real_today_plan, streak=streak_info, greeting=greeting
    )


# ==========================================
# STUDY PLAN ROUTES (SCREEN 9)
# ==========================================


@app.get("/users/me/plan", response_model=Optional[PlanResponse], status_code=status.HTTP_200_OK)
async def get_study_plan(
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    # 1. Fetch the user's most recently generated plan
    statement = select(StudyPlan).where(StudyPlan.user_id == current_user.id).order_by(StudyPlan.id.desc())
    db_plan = session.exec(statement).first()

    # If they have no plan in the database, return None to show the Goal Setup UI
    if not db_plan:
        return None 

    # 2. Fetch all study sessions linked to this plan
    sessions_statement = select(StudySession).where(StudySession.plan_id == db_plan.id)
    db_sessions = session.exec(sessions_statement).all()

    # 3. Calculate the stats required by the UI
    today = datetime.now().date()
    days_remaining = (db_plan.deadline - today).days
    
    # Calculate a rough daily target based on the generated sessions
    total_duration = sum(s.duration_mins for s in db_sessions)
    daily_target = total_duration // len(db_sessions) if db_sessions else 60

    stats = PlanStats(
        days_remaining=days_remaining if days_remaining > 0 else 0,
        daily_target_mins=daily_target,
        topics_count=len(db_sessions)
    )

    # 4. Construct the 7-day week array for the UI day-strip
    week = []
    for i in range(7):
        current_date = today + timedelta(days=i)
        date_str = current_date.isoformat()
        
        # Check if there is a session scheduled for this specific date
        day_session = next((s for s in db_sessions if s.date == date_str), None)
        
        week.append(WeekDay(
            date=date_str,
            day_label=current_date.strftime("%a").upper(), # e.g., "MON", "TUE"
            has_session=bool(day_session),
            session_type="study" if day_session else "rest"
        ))

    # 5. Format the sessions for the Flutter app
    formatted_sessions = [
        SessionDetail(
            id=str(s.id),
            date=s.date,
            time=s.time or "16:00",
            subject=s.subject,
            duration_mins=s.duration_mins,
            mode=s.mode,
            priority=s.priority,
            completed=s.completed
        ) for s in db_sessions
    ]

    # 6. Return the fully assembled plan
    return PlanResponse(
        goal=PlanGoal(subject=db_plan.subject, deadline=db_plan.deadline),
        stats=stats,
        week=week,
        sessions=formatted_sessions,
        nudge=None
    )

@app.post("/users/me/plan/generate", response_model=PlanResponse, status_code=status.HTTP_200_OK)
async def generate_study_plan(
    request: PlanGenerateRequest, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    days_remaining = (request.deadline - datetime.now().date()).days
    if days_remaining < 0:
        raise HTTPException(status_code=400, detail="Deadline passed.")

    ai_plan_data = await generate_deepseek_study_plan(goal=request.goal, target_date=request.deadline, days_remaining=days_remaining)
    if not ai_plan_data:
        raise HTTPException(status_code=500, detail="Failed to generate plan.")

    db_plan = StudyPlan(user_id=current_user.id, subject=request.goal, deadline=request.deadline, is_approved=False)
    session.add(db_plan)
    session.commit()
    session.refresh(db_plan)

    for ai_session in ai_plan_data.get("sessions", []):
        db_session = StudySession(
            plan_id=db_plan.id, user_id=current_user.id, date=ai_session["date"], time=ai_session.get("time", "12:00"), 
            subject=ai_session["subject"], duration_mins=ai_session["duration_mins"], mode=ai_session["mode"], priority=ai_session["priority"]
        )
        session.add(db_session)
        ai_session["id"] = f"ses_{uuid.uuid4().hex[:8]}"
        ai_session["completed"] = False
        
    session.commit()

    return PlanResponse(
        goal=PlanGoal(subject=request.goal, deadline=request.deadline),
        stats=ai_plan_data["stats"], week=ai_plan_data["week"], sessions=ai_plan_data["sessions"], nudge=None
    )

@app.patch("/users/me/plan/session/{session_id}", status_code=status.HTTP_200_OK)
async def update_session(
    session_id: int, request: SessionUpdateRequest, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    db_session = session.exec(select(StudySession).where(StudySession.id == session_id, StudySession.user_id == current_user.id)).first()
    if not db_session: raise HTTPException(status_code=404, detail="Session not found.")

    if request.scheduled_time is not None: db_session.time = request.scheduled_time
    if request.duration_mins is not None: db_session.duration_mins = request.duration_mins
    if request.skipped is not None: db_session.skipped = request.skipped

    session.add(db_session)
    session.commit()
    return db_session

@app.patch("/users/me/plan", status_code=status.HTTP_200_OK)
async def approve_study_plan(
    request: PlanApproveRequest, current_user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    db_plan = session.exec(select(StudyPlan).where(StudyPlan.user_id == current_user.id, StudyPlan.is_approved == False).order_by(StudyPlan.id.desc())).first()
    if not db_plan: raise HTTPException(status_code=404, detail="No pending plan.")
        
    db_plan.is_approved = request.approved
    session.add(db_plan)
    session.commit()
    return {"message": "Plan approved successfully"}


# ==========================================
# AI SOLVE ROUTES (SCREEN 10)
# ==========================================

@app.post("/solve", response_model=SolveResponse, status_code=status.HTTP_200_OK)
async def solve_question(request: SolveRequest, current_user: User = Depends(get_current_user)):
    if not request.question_text:
        raise HTTPException(status_code=400, detail="Please provide a question_text.")

    solution_data = await generate_deepseek_solution(request.question_text)
    if not solution_data:
        raise HTTPException(status_code=500, detail="Couldn't generate a solution. Try again.")

    return SolveResponse(**solution_data)

@app.post("/solve/{solution_id}/feedback", status_code=status.HTTP_200_OK)
async def submit_solution_feedback(solution_id: str, request: SolveFeedbackRequest, current_user: User = Depends(get_current_user)):
    print(f"Feedback for {solution_id}: Helpful? {request.helpful}. Reason: {request.flag_reason}")
    return {"acknowledged": True}