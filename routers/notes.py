# routers/notes.py
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
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

router = APIRouter(tags=["Notes Section"])

# Initialize DeepSeek Client
deepseek_client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", "your-deepseek-api-key"),
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

# --- AI Background Task for Flashcards ---
async def generate_cards_bg(note_id: int, user_id: int, options: GenerateCardsOptions, db: Session):
    print(f"Starting DeepSeek flashcard generation for note {note_id}...")
    
    note = db.get(Note, note_id)
    if not note or not note.content_text:
        return

    # Create the prompt based on user options
    focus_instruction = "Generate both definition-style cards and conceptual questions."
    if options.definitions and not options.questions:
        focus_instruction = "Generate ONLY definition-style vocabulary cards (Term -> Definition)."
    elif options.questions and not options.definitions:
        focus_instruction = "Generate ONLY conceptual question/answer cards. Do not generate simple vocabulary definitions."

    prompt = f"""
    You are an expert tutor. Create high-quality flashcards from the provided study notes.
    {focus_instruction}
    
    Return ONLY raw, valid JSON. Format strictly as:
    {{
      "cards": [
        {{
          "question": "The front of the card",
          "answer": "The back of the card (clear and concise)",
          "difficulty": "easy" | "medium" | "hard"
        }}
      ]
    }}
    
    NOTES TEXT:
    {note.content_text}
    """

    try:
        response = await deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an API that only returns valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        ai_data = json.loads(response.choices[0].message.content)
        cards_data = ai_data.get("cards", [])
        
        if not cards_data:
            return

        # 1. Ensure a StudySet exists for this note
        study_set = db.exec(select(StudySet).where(StudySet.title == f"Set: {note.title}")).first()
        if not study_set:
            study_set = StudySet(
                user_id=user_id,
                title=f"Set: {note.title}",
                subject=note.subject,
                card_count=0
            )
            db.add(study_set)
            db.commit()
            db.refresh(study_set)

        # 2. Add the generated cards to the DB
        for c in cards_data:
            new_card = Flashcard(
                study_set_id=study_set.id,
                note_id=note.id,
                question=c.get("question")[:200], # Truncate to DB limits just in case
                answer=c.get("answer")[:400],
                subject=note.subject,
                difficulty=c.get("difficulty", "medium")
            )
            db.add(new_card)
        
        # 3. Update counts
        study_set.card_count += len(cards_data)
        note.card_count += len(cards_data)
        
        db.commit()
        print(f"Successfully generated {len(cards_data)} cards for note {note_id}")

    except Exception as e:
        print(f"DeepSeek Error generating cards: {e}")


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
    """Delete note and ALL associated flashcards to avoid FK errors."""
    # 1. Verify Note exists and belongs to the user
    note = db.exec(select(Note).where(Note.id == note_id, Note.user_id == current_user.id)).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
        
    # 2. Delete all related Flashcards FIRST
    flashcards = db.exec(select(Flashcard).where(Flashcard.note_id == note_id)).all()
    for card in flashcards:
        db.delete(card)

    # 3. Safely delete the Note
    db.delete(note)
    db.commit()
    return {"message": "Note and its flashcards deleted successfully"}

# ==========================================
# 6. GENERATE CARDS (AI)
# ==========================================
@router.post("/notes/{note_id}/generate-cards", status_code=status.HTTP_200_OK)
async def generate_cards(
    note_id: int,
    payload: GenerateCardsRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Trigger AI flashcard generation from note text."""
    note = db.get(Note, note_id)
    if not note or note.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    # Rough estimate to show the user on the loading screen
    estimated_cards = max(1, note.word_count // 60)
    
    # Fire off the DeepSeek generation in the background!
    background_tasks.add_task(
        generate_cards_bg, 
        note.id, 
        current_user.id, 
        payload.options, 
        db
    )
    
    return {
        "set_id": f"temp_set_{note_id}", 
        "status": "processing", 
        "estimated_cards": estimated_cards
    }

# ==========================================
# 7. MANUALLY ADD CARD FROM HIGHLIGHT
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

    # Find or create a study set for this note
    study_set = db.exec(select(StudySet).where(StudySet.title == f"Set: {note.title}")).first()
    if not study_set:
        study_set = StudySet(user_id=current_user.id, title=f"Set: {note.title}", subject=note.subject)
        db.add(study_set)
        db.commit()
        db.refresh(study_set)

    new_card = Flashcard(
        study_set_id=study_set.id,
        note_id=note.id,
        question=payload.question,
        answer=payload.answer,
        subject=note.subject
    )
    db.add(new_card)
    
    study_set.card_count += 1
    note.card_count += 1
    
    db.commit()
    return {"message": "Card added to set successfully"}

# ==========================================
# 8. GET ALL CARDS FOR A NOTE
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