from sqlmodel import Session, select
from datetime import datetime
from models import User, UserTrophy, StudySession, DailyActivity, Collection, FeynmanSession

# A static dictionary of all possible trophies in your app
TROPHY_DICTIONARY = {
    "streak_3": {"title": "On a Roll", "description": "Hit a 3-day study streak", "icon": "🔥"},
    "streak_7": {"title": "Scholar", "description": "Hit a 7-day study streak", "icon": "⚡"},
    "feynman_first": {"title": "The Teacher", "description": "Complete your first Feynman session", "icon": "🧠"},
    "collection_creator": {"title": "Curator", "description": "Create your first collection", "icon": "📚"},
}

def check_and_award_trophies(user: User, db: Session):
    """
    Evaluates the user's current stats against the trophy rules.
    Awards any new trophies they have earned.
    """
    newly_earned = []
    
    # Fetch trophies the user already has so we don't award them twice
    existing_trophies = db.exec(
        select(UserTrophy.trophy_id).where(UserTrophy.user_id == user.id)
    ).all()
    earned_set = set(existing_trophies)

    # 🏆 RULE 1: STREAKS
    if user.current_streak >= 3 and "streak_3" not in earned_set:
        _award(user.id, "streak_3", db, newly_earned)
        
    if user.current_streak >= 7 and "streak_7" not in earned_set:
        _award(user.id, "streak_7", db, newly_earned)

    # 🏆 RULE 2: COLLECTIONS
    if "collection_creator" not in earned_set:
        # FIXED: Highly optimized query. Only selects the ID, stops after finding 1.
        has_collection = db.exec(select(Collection.id).where(Collection.user_id == user.id)).first()
        if has_collection:
            _award(user.id, "collection_creator", db, newly_earned)

    # 🏆 RULE 3: FEYNMAN (FIXED: Added missing logic)
    if "feynman_first" not in earned_set:
        has_feynman = db.exec(select(FeynmanSession.id).where(
            FeynmanSession.user_id == user.id, 
            FeynmanSession.is_complete == True
        )).first()
        
        if has_feynman:
            _award(user.id, "feynman_first", db, newly_earned)

    db.commit()
    return newly_earned

def _award(user_id: int, trophy_id: str, db: Session, tracker_list: list):
    """Helper to insert the trophy and track it for notifications"""
    new_trophy = UserTrophy(user_id=user_id, trophy_id=trophy_id)
    db.add(new_trophy)
    tracker_list.append(TROPHY_DICTIONARY[trophy_id])