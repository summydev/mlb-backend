# routers/canvas.py
import uuid
import asyncio
import json
import networkx as nx
from openai import AsyncOpenAI
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session, select
from typing import List
import os

# Import your schemas and models
from schemas import CanvasCreate, CanvasResponse, CanvasStatusResponse, NodeCreate, NodeResponse
from models import Canvas, CanvasNode, CanvasConnection, CanvasSourceType, Note
from security import get_current_user
from models import User
from database import get_session # explicitly importing the dependency

router = APIRouter(prefix="/canvases", tags=["canvases"])

# Initialize the Async DeepSeek Client
deepseek_client = AsyncOpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"), 
    base_url="https://api.deepseek.com"
)

# --- AI Processing Background Task ---

async def process_note_to_canvas_bg(canvas_id: uuid.UUID, note_content: str, db: Session):
    """
    Background task:
    1. Sends text to DeepSeek to extract nodes/edges as JSON.
    2. Uses NetworkX to calculate spatial (x,y) coordinates.
    3. Saves everything to the database.
    """
    print(f"Starting DeepSeek processing for canvas {canvas_id}...")
    
    # Fetch the canvas record to update it later
    canvas = db.exec(select(Canvas).where(Canvas.id == canvas_id)).first()
    if not canvas:
        print("Canvas not found, aborting background task.")
        return

    # ==========================================
    # STEP 1: DEEPSEEK LLM EXTRACTION
    # ==========================================
    prompt = f"""
    You are an expert educational AI. Analyze the following study notes and extract a mind map structure.
    Return ONLY raw, valid JSON. Do not use markdown blocks like ```json.
    
    Structure the JSON exactly like this:
    {{
      "hero_concept": "The single main topic (string)",
      "concepts": [
        {{ "id": "c1", "label": "Concept Name", "is_weak": false, "definition": "Short definition" }}
      ],
      "relationships": [
        {{ "from_id": "hero", "to_id": "c1", "label": "relates to" }},
        {{ "from_id": "c1", "to_id": "c2", "label": "produces" }}
      ]
    }}
    
    NOTES TO ANALYZE:
    {note_content}
    """

    try:
        response = await deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "You are an API that only returns valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"} # Forces strictly valid JSON
        )
        
        ai_data = json.loads(response.choices[0].message.content)
        
    except Exception as e:
        print(f"DeepSeek Error: {e}")
        return

    # ==========================================
    # STEP 2: SPATIAL LAYOUT (Force-Directed Graph)
    # ==========================================
    G = nx.Graph()
    
    G.add_node("hero")
    for concept in ai_data.get("concepts", []):
        G.add_node(concept["id"])
        
    for rel in ai_data.get("relationships", []):
        G.add_edge(rel["from_id"], rel["to_id"])
        
    positions = nx.spring_layout(G, center=(1500, 1500), scale=600, seed=42)

    # ==========================================
    # STEP 3: SAVE TO DATABASE
    # ==========================================
    id_map = {} 
    
    hero_uuid = uuid.uuid4()
    id_map["hero"] = hero_uuid
    hero_node = CanvasNode(
        id=hero_uuid,
        canvas_id=canvas_id,
        label=ai_data.get("hero_concept", "Main Topic")[:40],
        x=float(positions["hero"][0]),
        y=float(positions["hero"][1]),
        size="large",
        is_hero=True
    )
    db.add(hero_node)
    
    for concept in ai_data.get("concepts", []):
        node_uuid = uuid.uuid4()
        id_map[concept["id"]] = node_uuid
        
        node = CanvasNode(
            id=node_uuid,
            canvas_id=canvas_id,
            label=concept["label"][:40],
            x=float(positions[concept["id"]][0]),
            y=float(positions[concept["id"]][1]),
            size="medium",
            is_weak=concept.get("is_weak", False),
            definition=concept.get("definition")
        )
        db.add(node)
        
    for rel in ai_data.get("relationships", []):
        from_uuid = id_map.get(rel["from_id"])
        to_uuid = id_map.get(rel["to_id"])
        
        if from_uuid and to_uuid:
            connection = CanvasConnection(
                canvas_id=canvas_id,
                from_node_id=from_uuid,
                to_node_id=to_uuid,
                label=rel.get("label")
            )
            db.add(connection)
            
    canvas.node_count = len(ai_data.get("concepts", [])) + 1
    
    db.commit()
    print(f"Successfully processed and mapped canvas {canvas_id}!")


# --- API Endpoints ---

@router.post("/from-notes", response_model=CanvasStatusResponse)
def create_canvas_from_note(
    payload: CanvasCreate, 
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Trigger AI generation of a Canvas from an existing Note."""
    if not payload.note_id:
        raise HTTPException(status_code=400, detail="note_id is required")
        
    note = db.exec(select(Note).where(Note.id == payload.note_id, Note.user_id == current_user.id)).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
        
    db_canvas = Canvas(
        user_id=current_user.id, # Uses the real authenticated user!
        name=payload.name,
        subject=payload.subject,
        source_type=CanvasSourceType.notes,
        source_id=payload.note_id
    )
    db.add(db_canvas)
    db.commit()
    db.refresh(db_canvas)

    background_tasks.add_task(process_note_to_canvas_bg, db_canvas.id, note.content_text, db)
    
    return {"status": "processing", "node_count": 0, "nodes": []}

@router.get("/{canvas_id}/status", response_model=CanvasStatusResponse)
def get_canvas_status(
    canvas_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Polling endpoint for the AI Loading Screen."""
    # Ensure the user requesting status actually owns the canvas
    canvas = db.exec(select(Canvas).where(Canvas.id == canvas_id, Canvas.user_id == current_user.id)).first()
    if not canvas: 
        raise HTTPException(status_code=404, detail="Canvas not found")
    
    if canvas.node_count > 0:
        return {"status": "ready", "node_count": canvas.node_count, "nodes": canvas.nodes}
    else:
        return {"status": "processing", "node_count": 0, "nodes": []}

@router.post("", response_model=CanvasResponse)
def create_manual_canvas(
    payload: CanvasCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Create an empty canvas manually (no AI generation)."""
    db_canvas = Canvas(
        user_id=current_user.id, # Uses real authenticated user
        name=payload.name,
        subject=payload.subject,
        source_type=CanvasSourceType.manual
    )
    db.add(db_canvas)
    db.commit()
    db.refresh(db_canvas)
    
    return db_canvas

@router.post("/{canvas_id}/nodes", response_model=NodeResponse)
def add_node_to_canvas(
    canvas_id: uuid.UUID, 
    node: NodeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """Add a single node manually to an existing canvas."""
    # Verify ownership before adding nodes
    canvas = db.exec(select(Canvas).where(Canvas.id == canvas_id, Canvas.user_id == current_user.id)).first()
    if not canvas:
        raise HTTPException(status_code=404, detail="Canvas not found")

    db_node = CanvasNode(
        canvas_id=canvas_id,
        label=node.label,
        x=node.x,
        y=node.y,
        size=node.size,
        is_hero=node.is_hero,
        is_weak=node.is_weak
    )
    db.add(db_node)
    
    canvas.node_count += 1
    db.commit()
    db.refresh(db_node)
    
    return db_node