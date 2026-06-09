"""
Internal Chat API — 1:1 messaging between any team members.
Rules: Dealer cannot chat with another Dealer.
"""
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func

from app.auth.dependencies import get_active_tenant_user
from app.database import get_db
from app.models import (
    User, UserRole, ChatConversation, ChatMessage
)

router = APIRouter(prefix="/chat", tags=["Chat"])


# ─── Helpers ──────────────────────────────────────────────────

def make_key(uid_a, uid_b) -> str:
    ids = sorted([str(uid_a), str(uid_b)])
    return ids[0] + ":" + ids[1]


def can_chat(role_a: str, role_b: str) -> bool:
    """Dealer cannot chat with another Dealer."""
    if role_a == UserRole.DEALER and role_b == UserRole.DEALER:
        return False
    return True


def user_dict(u: User) -> dict:
    return {
        "id": str(u.id),
        "full_name": u.full_name,
        "email": u.email,
        "role": u.role,
        "role_label": (u.role or "").replace("_", " ").title(),
    }


# ─── List users I can chat with ────────────────────────────────

@router.get("/users")
def list_chattable_users(
    search: Optional[str] = None,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    """Return all users in the tenant that the current user can chat with."""
    q = db.query(User).filter(
        User.tenant_id == current_user.tenant_id,
        User.id != current_user.id,
        User.status == "active",
    )
    if search:
        q = q.filter(
            or_(User.full_name.ilike("%" + search + "%"),
                User.email.ilike("%" + search + "%"))
        )
    users = q.order_by(User.full_name).all()

    # Batch-load all conversations for current user in ONE query (avoid N+1)
    all_convs = db.query(ChatConversation).filter(
        ChatConversation.tenant_id == current_user.tenant_id,
        ChatConversation.conversation_key.contains(str(current_user.id)),
    ).all()
    conv_map = {c.conversation_key: c for c in all_convs}

    # Batch unread counts per conversation
    from sqlalchemy import case
    conv_ids = [c.id for c in all_convs]
    unread_map = {}
    if conv_ids:
        rows = db.query(
            ChatMessage.conversation_id,
            func.count(ChatMessage.id).label("cnt")
        ).filter(
            ChatMessage.conversation_id.in_(conv_ids),
            ChatMessage.sender_id != current_user.id,
            ChatMessage.is_read == False,
        ).group_by(ChatMessage.conversation_id).all()
        unread_map = {str(r.conversation_id): r.cnt for r in rows}

    result = []
    for u in users:
        if not can_chat(current_user.role, u.role):
            continue
        key = make_key(current_user.id, u.id)
        conv = conv_map.get(key)
        unread = unread_map.get(str(conv.id), 0) if conv else 0
        d = user_dict(u)
        d["unread"] = unread
        d["last_message"] = conv.last_message if conv else None
        d["last_message_at"] = conv.last_message_at.isoformat() if (conv and conv.last_message_at) else None
        result.append(d)

    # Sort: users with unread first, then by last message time
    result.sort(key=lambda x: (-(x["unread"] > 0), x["last_message_at"] or ""), reverse=False)
    result.sort(key=lambda x: x["unread"], reverse=True)
    return result


# ─── Get / Create Conversation ─────────────────────────────────

@router.get("/conversation/{other_user_id}")
def get_or_create_conversation(
    other_user_id: str,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    other = db.query(User).filter(
        User.id == other_user_id,
        User.tenant_id == current_user.tenant_id,
    ).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")
    if not can_chat(current_user.role, other.role):
        raise HTTPException(status_code=403, detail="Dealers cannot chat with other dealers")

    key = make_key(current_user.id, other.id)
    conv = db.query(ChatConversation).filter(
        ChatConversation.tenant_id == current_user.tenant_id,
        ChatConversation.conversation_key == key,
    ).first()

    if not conv:
        conv = ChatConversation(
            tenant_id=current_user.tenant_id,
            conversation_key=key,
            participant_a=current_user.id,
            participant_b=other.id,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    return {
        "conversation_id": str(conv.id),
        "other_user": user_dict(other),
        "last_message": conv.last_message,
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
    }


# ─── Get Messages ──────────────────────────────────────────────

@router.get("/conversation/{other_user_id}/messages")
def get_messages(
    other_user_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    key = make_key(current_user.id, other_user_id)
    conv = db.query(ChatConversation).filter(
        ChatConversation.tenant_id == current_user.tenant_id,
        ChatConversation.conversation_key == key,
    ).first()
    if not conv:
        return {"messages": [], "total": 0}

    total = db.query(ChatMessage).filter(ChatMessage.conversation_id == conv.id).count()
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conv.id)
        .order_by(ChatMessage.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    messages = list(reversed(messages))  # chronological order

    # Mark as read
    db.query(ChatMessage).filter(
        ChatMessage.conversation_id == conv.id,
        ChatMessage.sender_id != current_user.id,
        ChatMessage.is_read == False,
    ).update({"is_read": True})
    db.commit()

    return {
        "messages": [{
            "id": str(m.id),
            "sender_id": str(m.sender_id),
            "sender_name": m.sender_name,
            "sender_role": m.sender_role,
            "message": m.message,
            "is_read": m.is_read,
            "is_mine": str(m.sender_id) == str(current_user.id),
            "claim_ref": str(m.claim_ref) if m.claim_ref else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in messages],
        "total": total,
    }


# ─── Send Message ──────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    message: str
    claim_ref: Optional[str] = None


@router.post("/conversation/{other_user_id}/messages")
def send_message(
    other_user_id: str,
    body: SendMessageRequest,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if not body.message or not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    other = db.query(User).filter(
        User.id == other_user_id,
        User.tenant_id == current_user.tenant_id,
    ).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found")
    if not can_chat(current_user.role, other.role):
        raise HTTPException(status_code=403, detail="Dealers cannot chat with other dealers")

    key = make_key(current_user.id, other.id)
    conv = db.query(ChatConversation).filter(
        ChatConversation.tenant_id == current_user.tenant_id,
        ChatConversation.conversation_key == key,
    ).first()
    if not conv:
        conv = ChatConversation(
            tenant_id=current_user.tenant_id,
            conversation_key=key,
            participant_a=current_user.id,
            participant_b=other.id,
        )
        db.add(conv)
        db.flush()

    msg = ChatMessage(
        conversation_id=conv.id,
        sender_id=current_user.id,
        sender_name=current_user.full_name,
        sender_role=current_user.role,
        message=body.message.strip(),
        claim_ref=body.claim_ref or None,
    )
    db.add(msg)

    conv.last_message = body.message.strip()[:100]
    conv.last_message_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)

    return {
        "id": str(msg.id),
        "sender_id": str(msg.sender_id),
        "sender_name": msg.sender_name,
        "sender_role": msg.sender_role,
        "message": msg.message,
        "is_mine": True,
        "created_at": msg.created_at.isoformat(),
    }


# ─── Unread Count ──────────────────────────────────────────────

@router.get("/unread-count")
def unread_count(
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    convs = db.query(ChatConversation).filter(
        ChatConversation.tenant_id == current_user.tenant_id,
        or_(
            ChatConversation.participant_a == current_user.id,
            ChatConversation.participant_b == current_user.id,
        )
    ).all()
    total_unread = 0
    for conv in convs:
        total_unread += db.query(ChatMessage).filter(
            ChatMessage.conversation_id == conv.id,
            ChatMessage.sender_id != current_user.id,
            ChatMessage.is_read == False,
        ).count()
    return {"unread_count": total_unread}
