from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
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

router = APIRouter(prefix="/notes", tags=["Notes Section"])

client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

# ==========================================
# PYDANTIC SCHEMAS
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

class GenerateCardsRequest(BaseModel):
    options: dict = {"definitions": True, "questions": True}

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def calculate_note_metadata(text: str):
    """Calculates word count and generates the 80-char snippet."""
    word_count = len(text.split()) if text else 0
    snippet = text[:77] + "..." if len(text) > 80 else text
    return word_count, snippet

# ==========================================
# CORE CRUD ENDPOINTS
# ==========================================

@router.get("/", status_code=status.HTTP_200_OK)
async def get_all_notes(
    search: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """NL.1: Fetch paginated list of all user notes."""
    query = select(Note).where(Note.user_id == current_user.id)
    
    if search:
        # Simple search across title and content
        query = query.where(
            (Note.title.icontains(search)) | (Note.content_text.icontains(search))
        )
        
    # Sort by most recently updated
    query = query.order_by(Note.updated_at.desc()).offset(offset).limit(limit)
    notes = db.exec(query).all()
    
    # Count total notes for pagination
    total_count = db.exec(select(func.count(Note.id)).where(Note.user_id == current_user.id)).one()

    return {
        "notes": notes,
        "total_count": total_count,
        "has_more": total_count > (offset + limit)
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """NE.1: Create a new note (fires on first save in Note Editor)."""
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


@router.get("/{note_id}", status_code=status.HTTP_200_OK)
async def get_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """ND.1: Fetch full note content and metadata for Note Detail screen."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
        
    return note


@router.patch("/{note_id}", status_code=status.HTTP_200_OK)
async def update_note(
    note_id: int,
    payload: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """NE.1 & NS: Auto-save, manual save, rename, or subject change."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    # Update only the fields that were provided
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(note, key, value)
        
    # If content changed, recalculate the word count and snippet
    if "content_text" in update_data:
        note.word_count, note.snippet = calculate_note_metadata(note.content_text)

    note.updated_at = datetime.utcnow()
    db.add(note)
    db.commit()
    db.refresh(note)
    
    return {"note_id": note.id, "updated_at": note.updated_at}


@router.delete("/{note_id}", status_code=status.HTTP_200_OK)
async def delete_note(
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """NS: Soft delete note and ALL associated flashcards (via cascade)."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
        
    db.delete(note)
    db.commit()
    
    return {"message": "Note and linked flashcards deleted successfully"}


# ==========================================
# AI GENERATION ENDPOINTS
# ==========================================

@router.post("/{note_id}/generate-cards", status_code=status.HTTP_200_OK)
async def generate_cards_from_note(
    note_id: int,
    payload: GenerateCardsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    NE.1: Triggers AI flashcard generation from note text.
    *Note: In a heavy production app, this would use a Background Task and a Polling endpoint.
    For this implementation, we will await DeepSeek directly and return the created cards.*
    """
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
        
    if note.word_count < 10:
        raise HTTPException(status_code=400, detail="Note is too short to generate cards.")

    # 1. Ask DeepSeek to extract questions and answers via strict JSON
    system_prompt = f"""
    You are an expert tutor. Create a highly effective set of flashcards based ONLY on the following notes.
    Target subject: {note.subject}.
    
    Rules:
    - Keep questions under 150 characters.
    - Keep answers under 300 characters.
    - Return a valid JSON array of objects, where each object has a "question", "answer", and "difficulty" (easy/medium/hard).
    """

    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": note.content_text}
        ],
        response_format={"type": "json_object"}
    )
    
    # 2. Parse DeepSeek's JSON response
    # (Assuming DeepSeek returns {"cards": [{"question": "...", "answer": "...", "difficulty": "..."}]})
    try:
        ai_data = json.loads(response.choices[0].message.content)
        cards_data = ai_data.get("cards", [])
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to parse AI output.")

    if not cards_data:
        raise HTTPException(status_code=500, detail="AI could not find concepts to turn into cards.")

    # 3. Create a StudySet to hold these new cards
    study_set = StudySet(
        user_id=current_user.id,
        title=f"Notes: {note.title}",
        subject=note.subject,
        card_count=len(cards_data)
    )
    db.add(study_set)
    db.commit()
    db.refresh(study_set)

    # 4. Save the actual Flashcard rows to the database
    for c_data in cards_data:
        flashcard = Flashcard(
            study_set_id=study_set.id,
            note_id=note.id,  # Link it back to the note!
            question=c_data.get("question", "Unknown Concept"),
            answer=c_data.get("answer", "No answer generated"),
            subject=note.subject,
            difficulty=c_data.get("difficulty", "medium")
        )
        db.add(flashcard)
    
    # Update the note's card count
    note.card_count = len(cards_data)
    db.add(note)
    db.commit()

    return {
        "set_id": study_set.id,
        "status": "ready",
        "cards_generated": len(cards_data),
        "message": f"Successfully generated {len(cards_data)} flashcards!"
    }