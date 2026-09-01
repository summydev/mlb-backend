from fastapi import APIRouter, Depends, status
from sqlmodel import Session, select
from database import get_session
from security import get_current_user
from models import User, UserTrophy
from services.gamification import TROPHY_DICTIONARY, check_and_award_trophies

router = APIRouter(tags=["Trophies"])

# FIXED: Removed async for synchronous database operations
@router.get("/users/me/trophies", status_code=status.HTTP_200_OK)
def get_my_trophies(
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    # 1. Run a quick background check to see if they earned anything new just now
    check_and_award_trophies(current_user, db)

    # 2. Fetch all their earned trophies
    earned_records = db.exec(
        select(UserTrophy).where(UserTrophy.user_id == current_user.id).order_by(UserTrophy.earned_at.desc())
    ).all()

    # 3. Format the response using our dictionary
    earned_list = []
    earned_ids = set()
    
    for record in earned_records:
        t_data = TROPHY_DICTIONARY.get(record.trophy_id)
        if t_data:
            earned_list.append({
                "id": record.trophy_id,
                "title": t_data["title"],
                "description": t_data["description"],
                "icon": t_data["icon"],
                "earned_at": record.earned_at.isoformat()
            })
            earned_ids.add(record.trophy_id)

    # 4. Show locked trophies so the user knows what to strive for
    locked_list = []
    for t_id, t_data in TROPHY_DICTIONARY.items():
        if t_id not in earned_ids:
            locked_list.append({
                "id": t_id,
                "title": t_data["title"],
                "description": t_data["description"],
                "icon": "🔒" # Hidden icon for unearned trophies
            })

    return {
        "earned": earned_list,
        "locked": locked_list,
        "total_earned": len(earned_list),
        "total_available": len(TROPHY_DICTIONARY)
    }