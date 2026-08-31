from fastapi import APIRouter, Depends, status
from sqlmodel import Session, select
from database import get_session
from security import get_current_user
from models import User, Notification

router = APIRouter(tags=["Notifications"])

@router.get("/users/me/notifications", status_code=status.HTTP_200_OK)
async def get_my_notifications(current_user: User = Depends(get_current_user), db: Session = Depends(get_session)):
    """Fetch the authenticated user's notification history."""
    notifs = db.exec(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    ).all()
    return {"notifications": notifs}