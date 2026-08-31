from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import FastAPI, HTTPException, status, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
import os
import firebase_admin
import json
from firebase_admin import credentials
from typing import Optional, List

# Database and Models
from database import create_db_and_tables, get_session, engine
from models import User, Pet, StudyPlan, StudySession, DailyActivity, Quest, Feedback, UserTrophy 

# Security
from security import get_current_user

# Schemas
from schemas import (
    PetAdoptionRequest, FirstSessionUpdate,
    DashboardResponse, UserDashboardInfo, PetDashboardInfo, StreakInfo,
    PlanResponse, PlanGenerateRequest, SessionUpdateRequest, PlanApproveRequest,
    SolveRequest, SolveResponse, SolveFeedbackRequest, PlanGoal, TodayPlanSession,
    PlanStats, WeekDay, SessionDetail, FCMTokenUpdate
)

# AI Service
from ai_service import generate_deepseek_solution, generate_deepseek_study_plan

# Routers
from routers import collections, community, notifications, study, notes, canvas, profile, trophies, auth
from sqlalchemy import text

from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from routers.auth import limiter # Import the limiter we created in auth.py


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the Database
    create_db_and_tables()
    
    # Initialize Firebase Admin SDK securely via Environment Variable or local file
    firebase_json_str = os.getenv("FIREBASE_CREDENTIALS_JSON")
    
    try:
        if not firebase_admin._apps:
            if firebase_json_str:
                cred_dict = json.loads(firebase_json_str)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                print("🔥 Firebase initialized from Render ENV VAR!")
                
            elif os.path.exists("firebase-credentials.json"):
                cred = credentials.Certificate("firebase-credentials.json")
                firebase_admin.initialize_app(cred)
                print("🔥 Firebase initialized from LOCAL FILE!")
                
            else:
                print("⚠️ Firebase credentials not found. Push notifications disabled.")
                
    except Exception as e:
        print(f"❌ Error initializing Firebase: {e}")

    yield

app = FastAPI(title="myLB API", version="1.0", lifespan=lifespan)

# Register all feature routers
app.include_router(auth.router)
app.include_router(study.router)
app.include_router(notes.router) 
app.include_router(canvas.router)
app.include_router(collections.router)     
app.include_router(notifications.router)   
app.include_router(community.router)
app.include_router(trophies.router)
app.include_router(profile.router, prefix="/users/me", tags=["Profile"])

 

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# FIXED: CORS Middleware - Avoid wildcard with credentials
origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,https://app.mylb.com").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping", tags=["Health"])
def keep_alive():  # FIXED: Removed async for standard sync route
    return {"status": "myLB is awake and ready for beta testing!"}

# ==========================================
# HELPER: TIMEZONE
# ==========================================
def get_local_now(timezone_str: str = "UTC") -> datetime:
    try:
        tz = ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)

# ==========================================
# DATABASE UTILITIES
# ==========================================
# FIXED: Removed /admin/fix-db endpoint. 
# Use Alembic for migrations in production to avoid database locking during HTTP requests.

# ==========================================
# PROTECTED ONBOARDING & USER ROUTES
# ==========================================
# FIXED: Removed async to allow FastAPI to safely run sync DB calls in a threadpool
@app.post("/users/me/pet", status_code=status.HTTP_200_OK)
def adopt_pet(
    pet_data: PetAdoptionRequest, 
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    if session.exec(select(Pet).where(Pet.user_id == current_user.id)).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already adopted!")

    new_pet = Pet(user_id=current_user.id, pet_type=pet_data.pet_type, pet_name=pet_data.pet_name.strip())
    session.add(new_pet)
    session.commit()
    session.refresh(new_pet)
    return {"pet_id": new_pet.id, "pet_type": new_pet.pet_type, "pet_name": new_pet.pet_name, "level": new_pet.level, "xp": new_pet.xp}

@app.patch("/users/me", status_code=status.HTTP_200_OK)
def complete_tooltip_tour(
    update_data: FirstSessionUpdate, 
    current_user: User = Depends(get_current_user), 
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
def get_dashboard(
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session),
    x_timezone: str = Header("UTC")  # FIXED: Dynamic timezone handling
):
    local_now = get_local_now(x_timezone)
    hour = local_now.hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    
    user_info = UserDashboardInfo(
        first_name=current_user.name.split()[0] if current_user.name else "Student", 
        is_first_session=current_user.is_first_session 
    )

    today_str = local_now.date().isoformat()
    last_7_days = [(local_now.date() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    
    activities = session.exec(select(DailyActivity).where(
        DailyActivity.user_id == current_user.id, DailyActivity.date.in_(last_7_days)
    )).all()
    
    xp_map = {activity.date: activity.xp_earned for activity in activities}
    real_xp_history = [xp_map.get(day, 0) for day in last_7_days]
    
    streak_active = bool(xp_map.get(today_str, 0) > 0)

    # FIXED: Deduplicate dates with .distinct() to prevent false streak inflation
    all_active_dates = session.exec(
        select(DailyActivity.date)
        .where(DailyActivity.user_id == current_user.id, DailyActivity.xp_earned > 0)
        .distinct()
        .order_by(DailyActivity.date.desc())
    ).all()

    streak_count = 0
    check_date = local_now.date()

    if not streak_active:
        check_date -= timedelta(days=1)

    for active_date_str in all_active_dates:
        if active_date_str == check_date.isoformat():
            streak_count += 1
            check_date -= timedelta(days=1)
        elif active_date_str > check_date.isoformat():
            continue
        else:
            break

    streak_info = StreakInfo(days=streak_count, active_today=streak_active)

    pet = session.exec(select(Pet).where(Pet.user_id == current_user.id)).first()
    if pet:
        pet_info = PetDashboardInfo(
            name=pet.pet_name, type=pet.pet_type, level=pet.level, xp=pet.xp, 
            xp_to_next=1200, mood="happy", xp_history=real_xp_history 
        )
    else:
        pet_info = PetDashboardInfo(name="Nova", type="nova", level=1, xp=0, xp_to_next=1200, mood="happy", xp_history=[0]*7)

    today_sessions = session.exec(select(StudySession).where(
        StudySession.user_id == current_user.id, StudySession.date == today_str, StudySession.completed == False
    ).limit(4)).all()
    
    real_today_plan = [
        TodayPlanSession(id=str(s.id), subject=s.subject, duration_mins=s.duration_mins, mode=s.mode) 
        for s in today_sessions
    ]

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
def get_study_plan(
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session),
    x_timezone: str = Header("UTC")
):
    statement = select(StudyPlan).where(StudyPlan.user_id == current_user.id).order_by(StudyPlan.id.desc())
    db_plan = session.exec(statement).first()

    if not db_plan:
        return None 

    sessions_statement = select(StudySession).where(StudySession.plan_id == db_plan.id)
    db_sessions = session.exec(sessions_statement).all()

    today = get_local_now(x_timezone).date()
    days_remaining = (db_plan.deadline - today).days
    
    total_duration = sum(s.duration_mins for s in db_sessions)
    daily_target = total_duration // len(db_sessions) if db_sessions else 60

    stats = PlanStats(
        days_remaining=days_remaining if days_remaining > 0 else 0,
        daily_target_mins=daily_target,
        topics_count=len(db_sessions)
    )

    week = []
    for i in range(7):
        current_date = today + timedelta(days=i)
        date_str = current_date.isoformat()
        
        day_session = next((s for s in db_sessions if s.date == date_str), None)
        
        week.append(WeekDay(
            date=date_str,
            day_label=current_date.strftime("%a").upper(),
            has_session=bool(day_session),
            session_type="study" if day_session else "rest"
        ))

    formatted_sessions = [
        SessionDetail(
            id=str(s.id), date=s.date, time=s.time or "16:00", subject=s.subject,
            duration_mins=s.duration_mins, mode=s.mode, priority=s.priority, completed=s.completed
        ) for s in db_sessions
    ]

    return PlanResponse(
        goal=PlanGoal(subject=db_plan.subject, deadline=db_plan.deadline),
        stats=stats, week=week, sessions=formatted_sessions, nudge=None
    )

# MUST remain async because it awaits the DeepSeek AI service
@app.post("/users/me/plan/generate", response_model=PlanResponse, status_code=status.HTTP_200_OK)
async def generate_study_plan(
    request: PlanGenerateRequest, 
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session),
    x_timezone: str = Header("UTC")
):
    today = get_local_now(x_timezone).date()
    days_remaining = (request.deadline - today).days
    if days_remaining < 0:
        raise HTTPException(status_code=400, detail="Deadline passed.")

    ai_plan_data = await generate_deepseek_study_plan(goal=request.goal, target_date=request.deadline, days_remaining=days_remaining)
    if not ai_plan_data:
        raise HTTPException(status_code=500, detail="Failed to generate plan.")

    db_plan = StudyPlan(user_id=current_user.id, subject=request.goal, deadline=request.deadline, is_approved=False)
    session.add(db_plan)
    session.commit()
    session.refresh(db_plan)

    # FIXED: Commit DB session first to get real auto-incremented primary keys
    for ai_session in ai_plan_data.get("sessions", []):
        db_session = StudySession(
            plan_id=db_plan.id, user_id=current_user.id, date=ai_session["date"], time=ai_session.get("time", "12:00"), 
            subject=ai_session["subject"], duration_mins=ai_session["duration_mins"], mode=ai_session["mode"], priority=ai_session["priority"]
        )
        session.add(db_session)
        session.commit()
        session.refresh(db_session)
        
        # Use the real database ID for frontend mapping
        ai_session["id"] = str(db_session.id)
        ai_session["completed"] = False

    return PlanResponse(
        goal=PlanGoal(subject=request.goal, deadline=request.deadline),
        stats=ai_plan_data["stats"], week=ai_plan_data["week"], sessions=ai_plan_data["sessions"], nudge=None
    )

@app.patch("/users/me/plan/session/{session_id}", status_code=status.HTTP_200_OK)
def update_session(
    session_id: int, 
    request: SessionUpdateRequest, 
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    db_session = session.exec(select(StudySession).where(StudySession.id == session_id, StudySession.user_id == current_user.id)).first()
    if not db_session: raise HTTPException(status_code=404, detail="Session not found.")

    if request.scheduled_time is not None: db_session.time = request.scheduled_time
    if request.duration_mins is not None: db_session.duration_mins = request.duration_mins
    if request.skipped is not None: db_session.skipped = request.skipped

    session.add(db_session)
    session.commit()
    session.refresh(db_session)
    return db_session

# FIXED: Explicitly target the plan via plan_id to avoid approving the wrong draft
@app.patch("/users/me/plan/{plan_id}/approve", status_code=status.HTTP_200_OK)
def approve_study_plan(
    plan_id: int,
    request: PlanApproveRequest, 
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    db_plan = session.exec(select(StudyPlan).where(StudyPlan.id == plan_id, StudyPlan.user_id == current_user.id)).first()
    if not db_plan: raise HTTPException(status_code=404, detail="Plan not found.")
        
    db_plan.is_approved = request.approved
    session.add(db_plan)
    session.commit()
    return {"message": f"Plan {plan_id} approved status updated"}


# ==========================================
# AI SOLVE ROUTES (SCREEN 10)
# ==========================================
# MUST remain async because it awaits the DeepSeek AI service
@app.post("/solve", response_model=SolveResponse, status_code=status.HTTP_200_OK)
async def solve_question(request: SolveRequest, current_user: User = Depends(get_current_user)):
    if not request.question_text:
        raise HTTPException(status_code=400, detail="Please provide a question_text.")

    solution_data = await generate_deepseek_solution(request.question_text)
    if not solution_data:
        raise HTTPException(status_code=500, detail="Couldn't generate a solution. Try again.")

    return SolveResponse(**solution_data)

@app.post("/solve/{solution_id}/feedback", status_code=status.HTTP_200_OK)
def submit_solution_feedback(
    solution_id: str, 
    request: SolveFeedbackRequest, 
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    # FIXED: Persist the feedback record to the database
    new_feedback = Feedback(
        solution_id=solution_id,
        user_id=current_user.id,
        helpful=request.helpful,
        flag_reason=request.flag_reason
    )
    session.add(new_feedback)
    session.commit()
    
    print(f"✅ Feedback saved for {solution_id}: Helpful? {request.helpful}. Reason: {request.flag_reason}")
    return {"acknowledged": True}