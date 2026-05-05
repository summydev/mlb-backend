# routers/community.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, select, func, or_
from typing import List, Optional

from database import get_session
from security import get_current_user
from models import User, Collection

router = APIRouter(prefix="/community", tags=["Community Tab"])

@router.get("/collections", status_code=status.HTTP_200_OK)
async def get_discover_collections(
    search: Optional[str] = None,
    filter: str = Query("All"), # e.g., "Biology", "Law", or "Private"
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user), # Optional if you allow logged-out viewing
    db: Session = Depends(get_session)
):
    """
    DF: Fetch collections for the Discover Feed.
    Shows public and private collections, sorted by save_count (trending).
    """
    # 1. Base query: Only Public and Private (No 'shared' visibility)
    query = select(Collection).where(
        or_(Collection.visibility == "public", Collection.visibility == "private")
    )

    # 2. Search by title or subject
    if search:
        query = query.where(
            or_(
                Collection.title.icontains(search),
                Collection.subject.icontains(search)
            )
        )

    # 3. Apply Filters (Subject chips or the special "🔒 Private" chip)
    if filter and filter.lower() != "all":
        if filter.lower() == "private":
            query = query.where(Collection.visibility == "private")
        else:
            query = query.where(Collection.subject.ilike(filter))

    # 4. Sort by Trending (save_count descending) then by newest
    query = query.order_by(Collection.save_count.desc(), Collection.created_at.desc())

    # 5. Pagination
    offset = (page - 1) * limit
    collections = db.exec(query.offset(offset).limit(limit)).all()
    
    # Total count for pagination
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