"""
Knowledge / Tutorial Video API
Super Admin uploads CRM explainer and training videos.
All authenticated users can browse and watch published videos.
"""
import uuid as uuid_lib
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_active_tenant_user
from app.database import get_db
from app.models import User, UserRole, KnowledgeVideo

router = APIRouter(prefix="/knowledge", tags=["Knowledge Videos"])

UPLOAD_DIR = Path("uploads/knowledge")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_VIDEO_SIZE = 500 * 1024 * 1024  # 500 MB

CATEGORIES = {
    "overview":  "Platform Overview",
    "workflow":  "PDCN Workflow Guide",
    "dealer":    "Dealer Training",
    "cn_team":   "CN Team Guide",
    "finance":   "Finance Team Guide",
    "cfa":       "CFA Team Guide",
    "admin":     "Admin & Setup",
    "general":   "General",
}


def video_dict(v: KnowledgeVideo) -> dict:
    size_mb = round(v.file_size / 1024 / 1024, 1) if v.file_size else None
    mins, secs = divmod(v.duration_secs or 0, 60)
    duration_str = f"{mins}:{secs:02d}" if v.duration_secs else None
    return {
        "id": str(v.id),
        "title": v.title,
        "description": v.description,
        "category": v.category,
        "category_label": CATEGORIES.get(v.category, v.category),
        "filename": v.filename,
        "original_name": v.original_name,
        "file_size": v.file_size,
        "file_size_mb": size_mb,
        "duration_secs": v.duration_secs,
        "duration_str": duration_str,
        "mime_type": v.mime_type,
        "is_published": v.is_published,
        "sort_order": v.sort_order,
        "view_count": v.view_count,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


# ── Public browse (all authenticated users) ───────────────────
@router.get("/videos")
def list_videos(
    category: Optional[str] = None,
    published_only: bool = True,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    q = db.query(KnowledgeVideo)
    if published_only and current_user.role != UserRole.SUPER_ADMIN:
        q = q.filter(KnowledgeVideo.is_published == True)
    if category:
        q = q.filter(KnowledgeVideo.category == category)
    videos = q.order_by(KnowledgeVideo.sort_order, KnowledgeVideo.created_at.desc()).all()
    return {
        "videos": [video_dict(v) for v in videos],
        "categories": CATEGORIES,
        "total": len(videos),
    }



# ── Truly public endpoint for landing page (no auth) ─────────
from fastapi import APIRouter as _AR
# Override: expose /knowledge/videos as public for landing page
@router.get("/videos/public")
def list_public_videos_no_auth(
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """No-auth endpoint for landing page hero video player."""
    q = db.query(KnowledgeVideo).filter(KnowledgeVideo.is_published == True)
    if category:
        q = q.filter(KnowledgeVideo.category == category)
    videos = q.order_by(KnowledgeVideo.sort_order, KnowledgeVideo.created_at.desc()).all()
    return {
        "videos": [video_dict(v) for v in videos],
        "total": len(videos),
    }


@router.get("/videos/{filename}/public-stream")
def public_stream_video(
    filename: str,
    db: Session = Depends(get_db),
):
    """No-auth stream for landing page video player."""
    video = db.query(KnowledgeVideo).filter(
        KnowledgeVideo.filename == filename,
        KnowledgeVideo.is_published == True,
    ).first()
    if not video:
        raise HTTPException(404, "Video not found or not published")
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(404, "Video file not found")
    video.view_count = (video.view_count or 0) + 1
    db.commit()
    return FileResponse(str(file_path), media_type=video.mime_type or "video/mp4",
                        headers={"Accept-Ranges":"bytes","Cache-Control":"public, max-age=3600"})



# ── Stream / watch video ──────────────────────────────────────
@router.get("/videos/{filename}/stream")
def stream_video(
    filename: str,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    video = db.query(KnowledgeVideo).filter(KnowledgeVideo.filename == filename).first()
    if not video:
        raise HTTPException(404, "Video not found")
    if not video.is_published and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Video not available")

    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(404, "Video file not found on server")

    # Increment view count
    video.view_count = (video.view_count or 0) + 1
    db.commit()

    return FileResponse(
        str(file_path),
        media_type=video.mime_type or "video/mp4",
        headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"},
    )


# ── Super Admin: upload video ─────────────────────────────────
@router.post("/videos", status_code=201)
async def upload_video(
    title: str = Form(...),
    description: str = Form(""),
    category: str = Form("general"),
    is_published: bool = Form(False),
    sort_order: int = Form(0),
    file: UploadFile = File(...),
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    if not title.strip():
        raise HTTPException(400, "Title is required")

    content = await file.read()
    if len(content) > MAX_VIDEO_SIZE:
        raise HTTPException(400, "Video too large (max 500 MB)")

    ext = Path(file.filename).suffix.lower() or ".mp4"
    safe_name = str(uuid_lib.uuid4()) + ext
    (UPLOAD_DIR / safe_name).write_bytes(content)

    video = KnowledgeVideo(
        title=title.strip(),
        description=description.strip() or None,
        category=category,
        filename=safe_name,
        original_name=file.filename,
        file_size=len(content),
        mime_type=file.content_type or "video/mp4",
        is_published=is_published,
        sort_order=sort_order,
        uploaded_by=current_user.id,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video_dict(video)


# ── Super Admin: update metadata ──────────────────────────────
class VideoUpdateBody(BaseModel):
    title: str
    description: Optional[str] = None
    category: str = "general"
    is_published: bool = False
    sort_order: int = 0


@router.patch("/videos/{video_id}")
def update_video(
    video_id: str,
    body: VideoUpdateBody,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    video = db.query(KnowledgeVideo).filter(KnowledgeVideo.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")
    video.title = body.title.strip()
    video.description = body.description
    video.category = body.category
    video.is_published = body.is_published
    video.sort_order = body.sort_order
    video.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(video)
    return video_dict(video)


@router.post("/videos/{video_id}/publish")
def toggle_publish(
    video_id: str,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    video = db.query(KnowledgeVideo).filter(KnowledgeVideo.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")
    video.is_published = not video.is_published
    video.updated_at = datetime.utcnow()
    db.commit()
    return {"is_published": video.is_published}


@router.delete("/videos/{video_id}")
def delete_video(
    video_id: str,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    video = db.query(KnowledgeVideo).filter(KnowledgeVideo.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")
    try:
        (UPLOAD_DIR / video.filename).unlink(missing_ok=True)
    except Exception:
        pass
    db.delete(video)
    db.commit()
    return {"message": "Video deleted"}
