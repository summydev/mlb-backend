from fastapi import APIRouter, Depends, status, Query
from sqlmodel import Session, select, func, or_
from typing import Optional

from database import get_session
from security import get_current_user
from models import User, Collection

router = APIRouter(prefix="/community", tags=["Community Tab"])

@router.get("/collections", status_code=status.HTTP_200_OK)
async def get_discover_collections(
    search: Optional[str] = None,
    filter: str = Query("All"), 
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    query = select(Collection).where(
        or_(Collection.visibility == "public", Collection.visibility == "private")
    )

    if search:
        query = query.where(
            or_(Collection.title.icontains(search), Collection.subject.icontains(search))
        )

    if filter and filter.lower() != "all":
        if filter.lower() == "private":
            query = query.where(Collection.visibility == "private")
        else:
            query = query.where(Collection.subject.ilike(filter))

    query = query.order_by(Collection.save_count.desc(), Collection.created_at.desc())

    offset = (page - 1) * limit
    collections = db.exec(query.offset(offset).limit(limit)).all()
    
    total_count = db.exec(
        select(func.count(Collection.id)).where(
            or_(Collection.visibility == "public", Collection.visibility == "private")
        )
    ).one()

    return {
        "collections": collections,
        "total_count": total_count,
        "has_more": total_count > (offset + limit)
    }