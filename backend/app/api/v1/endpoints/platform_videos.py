"""Platform Knowledge Videos — Super Admin uploads, all roles watch."""
import uuid, os
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_active_tenant_user
from app.database import get_db
from app.models import User, UserRole, PlatformVideo

router = APIRouter(prefix="/platform-videos", tags=["Platform Videos"])

VID_DIR = Path("uploads/platform")
VID_DIR.mkdir(parents=True, exist_ok=True)
MAX_SIZE = 500 * 1024 * 1024  # 500 MB

CATEGORIES = {
    "overview":    "Platform Overview",
    "dealer":      "Dealer Guide",
    "cn_team":     "CN Team Guide",
    "finance":     "Finance Team Guide",
    "cfa":         "CFA Team Guide",
    "workflow":    "Workflow Tutorial",
    "reports":     "Reports & Exports",
    "faq":         "FAQ & Troubleshooting",
}


def vdict(v: PlatformVideo) -> dict:
    return {
        "id": str(v.id),
        "title": v.title,
        "description": v.description,
        "category": v.category,
        "category_label": CATEGORIES.get(v.category, v.category),
        "filename": v.filename,
        "original_name": v.original_name,
        "file_size": v.file_size,
        "mime_type": v.mime_type,
        "duration_secs": v.duration_secs,
        "is_published": v.is_published,
        "view_count": v.view_count,
        "target_roles": v.target_roles or "all",
        "sort_order": v.sort_order,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "stream_url": f"/api/v1/platform-videos/stream/{v.filename}",
    }


# ── Public: list published videos ─────────────────────────────
@router.get("/")
def list_videos(
    category: Optional[str] = None,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    q = db.query(PlatformVideo)
    # Non-admins only see published
    if current_user.role != UserRole.SUPER_ADMIN:
        q = q.filter(PlatformVideo.is_published == True)
    if category:
        q = q.filter(PlatformVideo.category == category)
    videos = q.order_by(PlatformVideo.sort_order, PlatformVideo.created_at.desc()).all()
    return {
        "videos": [vdict(v) for v in videos],
        "categories": CATEGORIES,
        "total": len(videos),
    }


# ── Admin: upload video ────────────────────────────────────────
@router.post("/", status_code=201)
async def upload_video(
    title: str = Form(...),
    description: str = Form(""),
    category: str = Form("overview"),
    target_roles: str = Form("all"),
    sort_order: int = Form(0),
    file: UploadFile = File(...),
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "File too large (max 500 MB)")
    ext = Path(file.filename).suffix.lower() or ".mp4"
    safe_name = str(uuid.uuid4()) + ext
    (VID_DIR / safe_name).write_bytes(content)
    v = PlatformVideo(
        title=title, description=description, category=category,
        filename=safe_name, original_name=file.filename,
        file_size=len(content), mime_type=file.content_type or "video/mp4",
        target_roles=target_roles, sort_order=sort_order,
        is_published=False, uploaded_by=current_user.id,
    )
    db.add(v); db.commit(); db.refresh(v)
    return vdict(v)


# ── Admin: update metadata ─────────────────────────────────────
class UpdateBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    target_roles: Optional[str] = None
    sort_order: Optional[int] = None
    is_published: Optional[bool] = None


@router.patch("/{vid_id}")
def update_video(
    vid_id: str, body: UpdateBody,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    v = db.query(PlatformVideo).filter(PlatformVideo.id == vid_id).first()
    if not v: raise HTTPException(404, "Not found")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(v, field, val)
    v.updated_at = datetime.utcnow()
    db.commit(); db.refresh(v)
    return vdict(v)


# ── Admin: delete ──────────────────────────────────────────────
@router.delete("/{vid_id}")
def delete_video(
    vid_id: str,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    v = db.query(PlatformVideo).filter(PlatformVideo.id == vid_id).first()
    if not v: raise HTTPException(404, "Not found")
    try: (VID_DIR / v.filename).unlink(missing_ok=True)
    except: pass
    db.delete(v); db.commit()
    return {"message": "Deleted"}


# ── Stream ─────────────────────────────────────────────────────
@router.get("/stream/{filename}")
def stream_video(
    filename: str,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    # Increment view count
    v = db.query(PlatformVideo).filter(PlatformVideo.filename == filename).first()
    if v:
        v.view_count = (v.view_count or 0) + 1
        db.commit()
    path = VID_DIR / filename
    if not path.exists(): raise HTTPException(404, "Video not found")
    return FileResponse(str(path), media_type="video/mp4",
                        headers={"Accept-Ranges": "bytes"})
