from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, select, func
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import json
import os
from openai import AsyncOpenAI

# Database, Models, and Authentication
from database import get_session
from security import get_current_user
from models import User, Note, Flashcard, StudySet

# Notice: No prefix! We will explicitly define the paths to prevent 307 Redirects
router = APIRouter(tags=["Notes Section"])

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

# ==========================================
# PYDANTIC SCHEMAS (Strictly matching the handoff)
# ==========================================

class NoteCreate(BaseModel):
    title: str = "Untitled note"
    subject: str
    content_text: str = ""
    content_html: Optional[str] = None

class NoteUpdate(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    content_text: Optional[str] = None
    content_html: Optional[str] = None
    is_public: Optional[bool] = None

class GenerateCardsOptions(BaseModel):
    definitions: bool = True
    questions: bool = True

class GenerateCardsRequest(BaseModel):
    options: GenerateCardsOptions

class ManualCardCreate(BaseModel):
    question: str
    answer: str

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def calculate_note_metadata(text: str):
    """Calculates word count and generates the 80-char snippet."""
    word_count = len(text.split()) if text else 0
    snippet = text[:77] + "..." if len(text) > 80 else text
    return word_count, snippet

# ==========================================
# 1. GET ALL NOTES
# ==========================================
@router.get("/users/me/notes", status_code=status.HTTP_200_OK)
async def get_all_notes(
    search: Optional[str] = None,
    sort: str = Query("recent"),
    filter: str = Query("all"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Fetch paginated list of all user notes."""
    query = select(Note).where(Note.user_id == current_user.id)
    
    # 1. Apply Search
    if search:
        query = query.where((Note.title.icontains(search)) | (Note.content_text.icontains(search)))
        
    # 2. Apply Subject Filter
    if filter.lower() != "all":
        query = query.where(Note.subject.ilike(filter))
        
    # 3. Apply Sorting
    if sort == "recent":
        query = query.order_by(Note.updated_at.desc())
    elif sort == "created":
        query = query.order_by(Note.created_at.desc())
    elif sort == "a-z":
        query = query.order_by(Note.title.asc())
    elif sort == "most-cards":
        query = query.order_by(Note.card_count.desc())
        
    # 4. Apply Pagination
    offset = (page - 1) * limit
    notes = db.exec(query.offset(offset).limit(limit)).all()
    
    # 5. Get Total Count
    total_count = db.exec(select(func.count(Note.id)).where(Note.user_id == current_user.id)).one()

    return {
        "notes": notes,
        "total_count": total_count,
        "has_more": total_count > (offset + limit)
    }

# ==========================================
# 2. CREATE NOTE
# ==========================================
@router.post("/notes", status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Create a new note (fires on first save in Note Editor)."""
    word_count, snippet = calculate_note_metadata(payload.content_text)
    
    new_note = Note(
        user_id=current_user.id,
        title=payload.title,
        subject=payload.subject,
        content_text=payload.content_text,
        content_html=payload.content_html,
        word_count=word_count,
        snippet=snippet
    )
    
    db.add(new_note)
    db.commit()
    db.refresh(new_note)
    
    return {"note_id": new_note.id, "created_at": new_note.created_at}

# ==========================================
# 3. GET NOTE DETAIL
# ==========================================
@router.get("/notes/{note_id}", status_code=status.HTTP_200_OK)
async def get_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Fetch full note content and metadata for Note Detail screen."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    return note

# ==========================================
# 4. UPDATE NOTE
# ==========================================
@router.patch("/notes/{note_id}", status_code=status.HTTP_200_OK)
async def update_note(
    note_id: int,
    payload: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Auto-save, manual save, rename, or subject change."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(note, key, value)
        
    if "content_text" in update_data:
        note.word_count, note.snippet = calculate_note_metadata(note.content_text)

    note.updated_at = datetime.utcnow()
    db.add(note)
    db.commit()
    return {"note_id": note.id, "updated_at": note.updated_at}

# ==========================================
# 5. DELETE NOTE
# ==========================================
@router.delete("/notes/{note_id}", status_code=status.HTTP_200_OK)
async def delete_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Soft delete note and ALL associated flashcards (via cascade)."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
        
    db.delete(note)
    db.commit()
    return {"message": "Note deleted successfully"}

# ==========================================
# 6. GENERATE CARDS (AI)
# ==========================================
@router.post("/notes/{note_id}/generate-cards", status_code=status.HTTP_200_OK)
async def generate_cards(
    note_id: int,
    payload: GenerateCardsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Trigger AI flashcard generation from note text."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    # In production, this would kick off a background task. 
    # For now, we return the processing status structure per the handoff.
    estimated_cards = max(1, note.word_count // 80)
    
    # TODO: Connect actual DeepSeek prompt generation here
    
    return {
        "set_id": f"mock_set_{note_id}", 
        "status": "processing", 
        "estimated_cards": estimated_cards
    }

# ==========================================
# 7. GENERATE CANVAS (AI)
# ==========================================
@router.post("/notes/{note_id}/generate-canvas", status_code=status.HTTP_200_OK)
async def generate_canvas(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Trigger AI Canvas (mind map) generation from note text."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    return {
        "canvas_id": f"mock_canvas_{note_id}", 
        "status": "processing"
    }

# ==========================================
# 8. GET GENERATION STATUS
# ==========================================
@router.get("/notes/{note_id}/status", status_code=status.HTTP_200_OK)
async def get_generation_status(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Check card/canvas generation status for the AI Processing screen."""
    # Mocking completion for the frontend to proceed
    return {"status": "ready"}

# ==========================================
# 9. MANUALLY ADD CARD FROM HIGHLIGHT
# ==========================================
@router.post("/notes/{note_id}/cards", status_code=status.HTTP_201_CREATED)
async def add_manual_card(
    note_id: int,
    payload: ManualCardCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Editor 'Add to card' selection action."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    # Create card logic here...
    return {"message": "Card added to set successfully"}

# ==========================================
# 10. GET ALL CARDS FOR A NOTE
# ==========================================
@router.get("/notes/{note_id}/cards", status_code=status.HTTP_200_OK)
async def get_note_cards(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Note Detail 'See all cards' link."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    cards = db.exec(select(Flashcard).where(Flashcard.note_id == note.id)).all()
    return {"cards": cards}