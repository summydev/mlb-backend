from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
import uuid
import json
from openai import AsyncOpenAI
import os  # <-- Add this
from dotenv import load_dotenv

# Database, Models, and Real Authentication!
from database import get_session
from security import get_current_user
from models import User, StudySet, Flashcard, FeynmanSession, DailyActivity, Pet

router = APIRouter(tags=["Study Tab"])
client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"), # Keep your real key here (use env variables in production!)
    base_url="https://api.deepseek.com"
)

# ==========================================
# PYDANTIC SCHEMAS (Request/Response Models)
# ==========================================

class SwipeResponse(BaseModel):
    card_id: int
    response: str 
    response_time_ms: Optional[int] = None

class FlashcardCompleteRequest(BaseModel):
    cards_correct: int
    cards_incorrect: int
    duration_seconds: int

class FeynmanStartRequest(BaseModel):
    set_id: int
    card_id: int

class FeynmanMessageRequest(BaseModel):
    message: str
    voice_transcript: Optional[str] = None

class FeynmanCompleteRequest(BaseModel):
    final_score: int
    duration_seconds: int

# ==========================================
# 6A: MODE SELECTION ENDPOINTS
# ==========================================

@router.get("/users/me/study-sets")
async def get_user_study_sets(
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    """Fetches all study sets belonging strictly to the authenticated user."""
    statement = select(StudySet).where(StudySet.user_id == current_user.id)
    return db.exec(statement).all()

@router.get("/study-sets/{set_id}")
async def get_study_set(
    set_id: int, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    study_set = db.get(StudySet, set_id)
    if not study_set or study_set.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Study set not found")
    return study_set

# ==========================================
# 6B: STANDARD FLASHCARDS ENDPOINTS
# ==========================================

@router.get("/study-sets/{set_id}/cards")
async def get_flashcards(
    set_id: int, 
    order: str = "spaced_repetition", 
    limit: int = 40, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    # Verify ownership before fetching cards
    study_set = db.get(StudySet, set_id)
    if not study_set or study_set.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Study set not found")

    query = select(Flashcard).where(Flashcard.study_set_id == set_id)
    
    if order == "spaced_repetition":
        query = query.order_by(Flashcard.is_weak.desc())
        
    cards = db.exec(query.limit(limit)).all()
    session_id = str(uuid.uuid4())

    return {
        "session_id": session_id,
        "total_cards": len(cards),
        "cards": cards
    }

@router.post("/sessions/{session_id}/responses")
async def record_swipe(
    session_id: str, 
    payload: SwipeResponse, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    card = db.get(Flashcard, payload.card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    if payload.response == "correct":
        card.is_weak = False
        xp_earned = 5  
        next_review = datetime.utcnow() + timedelta(days=3)
    elif payload.response == "incorrect":
        card.is_weak = True
        xp_earned = 1  
        next_review = datetime.utcnow() + timedelta(days=1)
    else:
        raise HTTPException(status_code=400, detail="Invalid response type")

    db.add(card)
    db.commit()

    return {
        "next_review_date": next_review.isoformat(),
        "xp_earned": xp_earned
    }

@router.post("/sessions/{session_id}/complete")
async def complete_flashcard_session(
    session_id: str, 
    payload: FlashcardCompleteRequest, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    base_xp = (payload.cards_correct * 5) + (payload.cards_incorrect * 1)
    pet_xp_awarded = int(base_xp * 0.5) 

    # 1. Update Pet XP
    pet = db.exec(select(Pet).where(Pet.user_id == current_user.id)).first()
    if pet:
        pet.xp += pet_xp_awarded
        db.add(pet)

    # 2. Update Daily Activity (Real Streak Data)
    today_str = datetime.now().date().isoformat()
    daily_activity = db.exec(select(DailyActivity).where(
        DailyActivity.user_id == current_user.id, 
        DailyActivity.date == today_str
    )).first()

    if daily_activity:
        daily_activity.xp_earned += base_xp
    else:
        daily_activity = DailyActivity(user_id=current_user.id, date=today_str, xp_earned=base_xp)
    
    db.add(daily_activity)
    db.commit()

    return {
        "session_summary": {
            "xp_earned": base_xp,
            "pet_xp": pet_xp_awarded,
            "streak_updated": True, 
            "next_suggestions": [
                {"label": "Tackle your weak cards", "action_type": "review_weak"},
                {"label": "Deep dive with Feynman", "action_type": "feynman_mode"}
            ]
        }
    }

# ==========================================
# 7: FEYNMAN MODE (AI CHAT) ENDPOINTS
# ==========================================

@router.post("/sessions/feynman/start")
async def start_feynman_session(
    payload: FeynmanStartRequest, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    card = db.get(Flashcard, payload.card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    # The mock is GONE! Using the real logged-in user ID
    feynman_session = FeynmanSession(
        user_id=current_user.id,
        study_set_id=payload.set_id,
        card_id=payload.card_id,
        comprehension_score=0
    )
    db.add(feynman_session)
    db.commit()
    db.refresh(feynman_session)

    first_prompt = f"Explain {card.question} as if I've never heard of it before. Break it down simply!"

    return {
        "session_id": feynman_session.id,
        "first_prompt": first_prompt,
        "card_concept": card.subject
    }

@router.post("/sessions/feynman/{session_id}/message")
async def feynman_chat_message(
    session_id: int, 
    payload: FeynmanMessageRequest, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    feynman_session = db.get(FeynmanSession, session_id)
    
    # Security check: ensure this chat belongs to the user
    if not feynman_session or feynman_session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
        
    card = db.get(Flashcard, feynman_session.card_id)
    user_input = payload.voice_transcript if payload.voice_transcript else payload.message

    system_prompt = f"""
    You are the 'myLB AI Feynman Coach', an expert tutor testing a student's comprehension.
    The concept they must explain is: "{card.question}". 
    The correct technical answer is: "{card.answer}".

    Your current state:
    - Previous Score: {feynman_session.comprehension_score}/100
    - Previous Gaps: {feynman_session.gaps_identified}

    INSTRUCTIONS:
    1. Read the student's explanation.
    2. Respond with an encouraging, conversational tone (max 3 sentences). 
    3. If they missed something, ask a probing follow-up question.
    4. Calculate a live comprehension score (0-100).
    5. Calculate the score_delta (+/- change from the previous score).
    6. Update the arrays of strong_points and gaps_identified.
    7. Set 'session_complete' to true ONLY IF the score is > 90 AND they have covered all core concepts.

    YOU MUST RESPOND ONLY IN VALID JSON FORMAT matching this structure:
    {{
      "ai_reply": "Your conversational reply here",
      "comprehension_score": int,
      "score_delta": int,
      "session_complete": bool,
      "gaps_identified": ["gap 1", "gap 2"],
      "strong_points": ["point 1"]
    }}
    """

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ],
        response_format={"type": "json_object"}
    )

    ai_data = json.loads(response.choices[0].message.content)

    feynman_session.comprehension_score = ai_data["comprehension_score"]
    feynman_session.is_complete = ai_data["session_complete"]
    feynman_session.gaps_identified = json.dumps(ai_data["gaps_identified"])
    feynman_session.strong_points = json.dumps(ai_data["strong_points"])
    
    db.add(feynman_session)
    db.commit()

    return {
        "ai_reply": ai_data["ai_reply"],
        "comprehension_score": ai_data["comprehension_score"],
        "score_delta": ai_data["score_delta"],
        "session_complete": ai_data["session_complete"]
    }

@router.get("/sessions/feynman/{session_id}/score")
async def get_feynman_score(
    session_id: int, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    session = db.get(FeynmanSession, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
        
    return {
        "comprehension_score": session.comprehension_score,
        "gaps_identified": json.loads(session.gaps_identified),
        "strong_points": json.loads(session.strong_points)
    }

@router.post("/sessions/feynman/{session_id}/complete")
async def complete_feynman_session(
    session_id: int, 
    payload: FeynmanCompleteRequest, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    feynman_session = db.get(FeynmanSession, session_id)
    if not feynman_session or feynman_session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")
        
    feynman_session.is_complete = True
    db.add(feynman_session)

    # 1. Record XP
    base_xp = payload.final_score 
    pet_xp = int(base_xp * 0.5)

    # 2. Update Daily Activity Table
    today_str = datetime.now().date().isoformat()
    daily_activity = db.exec(select(DailyActivity).where(
        DailyActivity.user_id == current_user.id, 
        DailyActivity.date == today_str
    )).first()

    if daily_activity:
        daily_activity.xp_earned += base_xp
    else:
        daily_activity = DailyActivity(user_id=current_user.id, date=today_str, xp_earned=base_xp)
    
    db.add(daily_activity)
    
    # 3. Update Pet Table
    pet = db.exec(select(Pet).where(Pet.user_id == current_user.id)).first()
    if pet:
        pet.xp += pet_xp
        db.add(pet)

    db.commit()

    return {
        "session_summary": {
            "xp_earned": base_xp,
            "pet_xp": pet_xp,
            "comprehension_score": payload.final_score,
            "next_suggestions": [
                {"label": "Review your gaps", "action_type": "review_gaps"}
            ]
        }
    }