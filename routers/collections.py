from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import Session, select, func
from typing import List, Optional
from pydantic import BaseModel

# Database, Models, and Auth
from database import get_session
from security import get_current_user
from models import (
    User, Collection, CollectionItem, CollectionAccess, CollectionRequest,
    Note, StudySet, Canvas, CanvasConnection, CanvasNode, Flashcard
)
from services.notifications import send_collection_notification
from schemas import CollectionUpdate, ItemReorderRequest

# NOTE: No prefix here so we can mix /users/me/ routes and /collections/ routes
router = APIRouter(tags=["Collections Section"])

class CollectionCreate(BaseModel):
    title: str
    subject: str
    visibility: str # "private", "shared", "public"
    description: Optional[str] = None
    cover_emoji: Optional[str] = None
    item_ids: List[str] = [] 
    item_types: List[str] = [] 

class ItemAddRequest(BaseModel):
    item_id: str
    item_type: str 

class InviteRequest(BaseModel):
    emails: List[str]

class AccessRequestSubmit(BaseModel):
    message: Optional[str] = None

class DenyRequest(BaseModel):
    reason: Optional[str] = None

class SaveItemRequest(BaseModel):
    item_id: str
    item_type: str

class ReportRequest(BaseModel):
    reason: str


# ==========================================
# 1. MY COLLECTIONS LIBRARY (COL-L)
# ==========================================
@router.get("/users/me/collections", status_code=status.HTTP_200_OK)
async def get_my_collections(
    search: Optional[str] = None,
    sort: str = Query("recent"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    query = select(Collection).where(Collection.user_id == current_user.id)
    if search:
        query = query.where(Collection.title.icontains(search))
    query = query.order_by(Collection.updated_at.desc())
    
    offset = (page - 1) * limit
    collections = db.exec(query.offset(offset).limit(limit)).all()
    total_count = db.exec(select(func.count(Collection.id)).where(Collection.user_id == current_user.id)).one()

    return {
        "collections": collections,
        "total_count": total_count,
        "has_more": total_count > (offset + limit)
    }

# ==========================================
# 2. CREATE & EDIT COLLECTION
# ==========================================
@router.post("/collections", status_code=status.HTTP_201_CREATED)
async def create_collection(
    payload: CollectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    new_collection = Collection(
        user_id=current_user.id, title=payload.title, subject=payload.subject,
        visibility=payload.visibility, description=payload.description, cover_emoji=payload.cover_emoji
    )
    db.add(new_collection)
    db.commit()
    db.refresh(new_collection)

    if payload.item_ids and len(payload.item_ids) == len(payload.item_types):
        for i in range(len(payload.item_ids)):
            new_item = CollectionItem(
                collection_id=new_collection.id, item_type=payload.item_types[i],
                item_id=payload.item_ids[i], position=i
            )
            db.add(new_item)
        db.commit()

    return {"collection_id": new_collection.id, "share_token": new_collection.share_token, "message": "Collection created successfully"}

@router.get("/collections/{collection_id}", status_code=status.HTTP_200_OK)
async def get_collection_detail(
    collection_id: int, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection: raise HTTPException(status_code=404, detail="Collection not found")
        
    if collection.user_id != current_user.id and collection.visibility != "public":
        access = db.exec(select(CollectionAccess).where(CollectionAccess.collection_id == collection.id, CollectionAccess.user_id == current_user.id)).first()
        if not access: raise HTTPException(status_code=403, detail="You do not have access to this collection")

    item_mappings = db.exec(select(CollectionItem).where(CollectionItem.collection_id == collection.id).order_by(CollectionItem.position)).all()
    resolved_items = []
    
    for mapping in item_mappings:
        if mapping.item_type == "note":
            note = db.get(Note, int(mapping.item_id))
            if note: resolved_items.append({"id": str(note.id), "type": "note", "title": note.title, "subject": note.subject})
        elif mapping.item_type == "set":
            study_set = db.get(StudySet, int(mapping.item_id))
            if study_set: resolved_items.append({"id": str(study_set.id), "type": "set", "title": study_set.title, "card_count": study_set.card_count})
        elif mapping.item_type == "canvas":
            import uuid
            canvas = db.get(Canvas, uuid.UUID(mapping.item_id))
            if canvas: resolved_items.append({"id": str(canvas.id), "type": "canvas", "title": canvas.name, "node_count": canvas.node_count})

    return {"collection": collection, "items": resolved_items}

@router.patch("/collections/{collection_id}", status_code=status.HTTP_200_OK)
async def update_collection_settings(
    collection_id: int, payload: CollectionUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items(): setattr(collection, key, value)
        
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return {"message": "Collection updated successfully"}

@router.delete("/collections/{collection_id}", status_code=status.HTTP_200_OK)
async def delete_collection(
    collection_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    items = db.exec(select(CollectionItem).where(CollectionItem.collection_id == collection.id)).all()
    for item in items: db.delete(item)

    access_rows = db.exec(select(CollectionAccess).where(CollectionAccess.collection_id == collection.id)).all()
    for row in access_rows: db.delete(row)
        
    req_rows = db.exec(select(CollectionRequest).where(CollectionRequest.collection_id == collection.id)).all()
    for row in req_rows: db.delete(row)

    db.delete(collection)
    db.commit()
    return {"message": "Collection deleted successfully. Your items are safe."}


# ==========================================
# 3. MANAGE ITEMS IN A COLLECTION
# ==========================================
@router.post("/collections/{collection_id}/items", status_code=status.HTTP_200_OK)
async def add_item_to_collection(
    collection_id: int, payload: ItemAddRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    existing_item = db.exec(select(CollectionItem).where(
        CollectionItem.collection_id == collection.id, CollectionItem.item_id == payload.item_id, CollectionItem.item_type == payload.item_type
    )).first()

    if existing_item: return {"message": "Item already in collection"}

    max_pos = db.exec(select(func.max(CollectionItem.position)).where(CollectionItem.collection_id == collection.id)).one()
    next_pos = (max_pos or 0) + 1

    new_item = CollectionItem(collection_id=collection.id, item_type=payload.item_type, item_id=payload.item_id, position=next_pos)
    db.add(new_item)
    db.commit()
    return {"message": "Item added successfully"}

@router.patch("/collections/{collection_id}/items", status_code=status.HTTP_200_OK)
async def reorder_collection_items(
    collection_id: int, payload: ItemReorderRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    for reorder_item in payload.positions:
        mapping = db.exec(select(CollectionItem).where(
            CollectionItem.collection_id == collection.id, CollectionItem.item_id == reorder_item.item_id
        )).first()
        if mapping:
            mapping.position = reorder_item.position
            db.add(mapping)
            
    db.commit()
    return {"message": "Items reordered successfully"}


# ==========================================
# 4. SHARE SETTINGS: LINKS & INVITES
# ==========================================
@router.post("/collections/{collection_id}/share-token/regenerate", status_code=status.HTTP_200_OK)
async def regenerate_share_token(
    collection_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    import uuid
    collection.share_token = uuid.uuid4().hex[:12]
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return {"new_share_token": collection.share_token}

@router.post("/collections/{collection_id}/invites", status_code=status.HTTP_200_OK)
async def invite_users_by_email(
    collection_id: int, payload: InviteRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    invited, already_had_access, not_found = [], [], []

    for email in payload.emails:
        user = db.exec(select(User).where(User.email == email.lower())).first()
        if not user:
            not_found.append(email)
            continue
            
        existing_access = db.exec(select(CollectionAccess).where(CollectionAccess.collection_id == collection.id, CollectionAccess.user_id == user.id)).first()

        if existing_access:
            already_had_access.append(email)
        else:
            new_access = CollectionAccess(collection_id=collection.id, user_id=user.id)
            db.add(new_access)
            invited.append(email)
            
            send_collection_notification(
                db=db, user_id=user.id, title="Collection Invitation",
                body=f"@{current_user.name} invited you to '{collection.title}'.", deep_link=f"/collections/{collection.id}/view"
            )

    db.commit()
    return {"invited": invited, "already_had_access": already_had_access, "not_found": not_found}

@router.delete("/collections/{collection_id}/access/{user_id}", status_code=status.HTTP_200_OK)
async def revoke_access(
    collection_id: int, user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    access_record = db.exec(select(CollectionAccess).where(CollectionAccess.collection_id == collection.id, CollectionAccess.user_id == user_id)).first()

    if access_record:
        db.delete(access_record)
        db.commit()
        send_collection_notification(
            db=db, user_id=user_id, title="Access Removed",
            body=f"Your access to '{collection.title}' has been removed by @{current_user.name}.", deep_link=None
        )
    return {"message": "Access revoked successfully"}


# ==========================================
# 5. ACCESS REQUESTS
# ==========================================
@router.post("/collections/{collection_id}/requests", status_code=status.HTTP_200_OK)
async def submit_access_request(
    collection_id: int, payload: AccessRequestSubmit, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection: raise HTTPException(status_code=404)

    existing_req = db.exec(select(CollectionRequest).where(
        CollectionRequest.collection_id == collection.id, CollectionRequest.user_id == current_user.id, CollectionRequest.status == "pending"
    )).first()

    if existing_req: return {"message": "Request already pending"}

    new_request = CollectionRequest(collection_id=collection.id, user_id=current_user.id, message=payload.message)
    db.add(new_request)
    db.commit()

    send_collection_notification(
        db=db, user_id=collection.user_id, title="New Access Request",
        body=f"{current_user.name} wants access to '{collection.title}'", deep_link=f"/collections/{collection.id}/share"
    )
    return {"message": "Request sent successfully"}

@router.get("/collections/{collection_id}/requests", status_code=status.HTTP_200_OK)
async def get_pending_requests(
    collection_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    requests = db.exec(select(CollectionRequest, User).join(User, CollectionRequest.user_id == User.id).where(
        CollectionRequest.collection_id == collection.id, CollectionRequest.status == "pending"
    )).all()

    formatted_requests = [{"request_id": req.id, "user_id": user.id, "username": user.name, "email": user.email, "message": req.message, "requested_at": req.requested_at} for req, user in requests]
    return {"requests": formatted_requests}

@router.post("/collections/{collection_id}/requests/{request_id}/approve", status_code=status.HTTP_200_OK)
async def approve_request(
    collection_id: int, request_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    req = db.exec(select(CollectionRequest).where(CollectionRequest.id == request_id)).first()
    if not req: raise HTTPException(status_code=404)

    req.status = "approved"
    db.add(req)

    existing_access = db.exec(select(CollectionAccess).where(CollectionAccess.collection_id == collection.id, CollectionAccess.user_id == req.user_id)).first()
    if not existing_access:
        new_access = CollectionAccess(collection_id=collection.id, user_id=req.user_id)
        db.add(new_access)

    db.commit()
    send_collection_notification(
        db=db, user_id=req.user_id, title="Access Granted!",
        body=f"@{current_user.name} approved your access to '{collection.title}' — open it now!", deep_link=f"/collections/{collection.id}/view"
    )
    return {"message": "Request approved"}

@router.post("/collections/{collection_id}/requests/{request_id}/deny", status_code=status.HTTP_200_OK)
async def deny_request(
    collection_id: int, request_id: int, payload: DenyRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection or collection.user_id != current_user.id: raise HTTPException(status_code=404)

    req = db.exec(select(CollectionRequest).where(CollectionRequest.id == request_id)).first()
    if not req: raise HTTPException(status_code=404)

    req.status = "denied"
    db.add(req)
    db.commit()

    send_collection_notification(
        db=db, user_id=req.user_id, title="Access Denied",
        body=f"Your request to '{collection.title}' was not approved.", deep_link=None
    )
    return {"message": "Request denied"}


# ==========================================
# 6. ITEM PICKER & VIEWER ACTIONS
# ==========================================
@router.get("/users/me/content", status_code=status.HTTP_200_OK)
async def get_user_content_for_picker(
    types: str = Query("notes,sets,canvases"), search: Optional[str] = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    requested_types = types.split(",")
    content = []

    if "notes" in requested_types:
        q = select(Note).where(Note.user_id == current_user.id)
        if search: q = q.where(Note.title.icontains(search))
        notes = db.exec(q).all()
        for n in notes: content.append({"id": str(n.id), "type": "note", "title": n.title, "date": n.created_at})

    if "sets" in requested_types:
        q = select(StudySet).where(StudySet.user_id == current_user.id)
        if search: q = q.where(StudySet.title.icontains(search))
        sets = db.exec(q).all()
        for s in sets: content.append({"id": str(s.id), "type": "set", "title": s.title, "date": s.created_at})

    if "canvases" in requested_types:
        q = select(Canvas).where(Canvas.user_id == current_user.id)
        if search: q = q.where(Canvas.name.icontains(search))
        canvases = db.exec(q).all()
        for c in canvases: content.append({"id": str(c.id), "type": "canvas", "title": c.name, "date": c.created_at})

    content.sort(key=lambda x: x["date"], reverse=True)
    return {"items": content}

@router.post("/collections/{collection_id}/save", status_code=status.HTTP_200_OK)
async def save_public_collection(
    collection_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    collection = db.get(Collection, collection_id)
    if not collection: raise HTTPException(status_code=404)
    if collection.visibility != "public": raise HTTPException(status_code=403, detail="Only public collections can be saved")

    collection.save_count += 1
    db.add(collection)
    db.commit()
    return {"message": "Collection saved to your library", "save_count": collection.save_count}

@router.post("/users/me/library/items", status_code=status.HTTP_200_OK)
async def save_individual_item(
    payload: SaveItemRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)
):
    if payload.item_type == "note":
        original = db.get(Note, int(payload.item_id))
        if not original: raise HTTPException(status_code=404)
        new_note = Note(
            user_id=current_user.id, title=original.title, subject=original.subject, 
            content_text=original.content_text, content_html=original.content_html, word_count=original.word_count, snippet=original.snippet
        )
        db.add(new_note)
        
    elif payload.item_type == "set":
        original_set = db.get(StudySet, int(payload.item_id))
        if not original_set: raise HTTPException(status_code=404)
        
        new_set = StudySet(user_id=current_user.id, title=original_set.title, subject=original_set.subject, card_count=original_set.card_count)
        db.add(new_set)
        db.commit() 
        
        original_cards = db.exec(select(Flashcard).where(Flashcard.study_set_id == original_set.id)).all()
        for old_card in original_cards:
            new_card = Flashcard(
                study_set_id=new_set.id, question=old_card.question, answer=old_card.answer, subject=old_card.subject, difficulty=old_card.difficulty
            )
            db.add(new_card)

    elif payload.item_type == "canvas":
        import uuid
        original_canvas = db.get(Canvas, uuid.UUID(payload.item_id))
        if not original_canvas: raise HTTPException(status_code=404)
        
        new_canvas = Canvas(user_id=current_user.id, name=original_canvas.name, subject=original_canvas.subject, source_type="manual")
        db.add(new_canvas)
        db.commit()
        
        original_nodes = db.exec(select(CanvasNode).where(CanvasNode.canvas_id == original_canvas.id)).all()
        id_map = {}
        for old_node in original_nodes:
            new_node = CanvasNode(
                canvas_id=new_canvas.id, label=old_node.label, x=old_node.x, y=old_node.y, size=old_node.size, is_hero=old_node.is_hero
            )
            db.add(new_node)
            db.commit() 
            id_map[old_node.id] = new_node.id
            
        original_connections = db.exec(select(CanvasConnection).where(CanvasConnection.canvas_id == original_canvas.id)).all()
        for old_conn in original_connections:
            if old_conn.from_node_id in id_map and old_conn.to_node_id in id_map:
                new_conn = CanvasConnection(
                    canvas_id=new_canvas.id, from_node_id=id_map[old_conn.from_node_id], to_node_id=id_map[old_conn.to_node_id], label=old_conn.label
                )
                db.add(new_conn)

    db.commit()
    return {"message": f"{payload.item_type.capitalize()} saved to your library"}

@router.get("/collections/by-token/{share_token}", status_code=status.HTTP_200_OK)
async def get_collection_metadata_by_token(share_token: str, db: Session = Depends(get_session)):
    collection = db.exec(select(Collection).where(Collection.share_token == share_token)).first()
    if not collection: raise HTTPException(status_code=404, detail="Link invalid or expired")
    owner = db.get(User, collection.user_id)
    return {"collection_id": collection.id, "title": collection.title, "owner_username": owner.name if owner else "Unknown User", "visibility": collection.visibility}

@router.get("/collections/{collection_id}/requests/my", status_code=status.HTTP_200_OK)
async def check_my_request_status(collection_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)):
    req = db.exec(select(CollectionRequest).where(
        CollectionRequest.collection_id == collection_id, CollectionRequest.user_id == current_user.id
    ).order_by(CollectionRequest.id.desc())).first()
    return {"status": req.status if req else "none"}

@router.post("/collections/{collection_id}/report", status_code=status.HTTP_200_OK)
async def report_collection(collection_id: int, payload: ReportRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_session)):
    print(f"Collection {collection_id} reported by {current_user.id} for: {payload.reason}")
    return {"message": "Collection reported. Our team will review it."}