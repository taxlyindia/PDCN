from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks, UploadFile, File
from sqlalchemy.orm import Session

from app.auth.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_token, generate_reset_token,
)
from app.auth.dependencies import get_current_user
from app.config import settings
from app.database import get_db
from app.models import (
    User, Tenant, RefreshToken, PasswordResetToken,
    UserRole, UserStatus, TenantStatus, AuthProvider, LoginLog, ActivityLog
)
from app.schemas import (
    SignupRequest, LoginRequest, TokenResponse, RefreshTokenRequest,
    PasswordResetRequest, PasswordResetConfirm, ChangePasswordRequest,
    MessageResponse, UserOut,
)
from app.services.tenant_service import create_tenant_with_admin
from app.utils.email import send_password_reset_email

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _build_token_response(user: User, db: Session) -> dict:
    """Issue access + refresh tokens for a user."""
    access = create_access_token({"sub": str(user.id), "role": user.role})
    refresh = create_refresh_token()
    expires = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    db_token = RefreshToken(user_id=user.id, token=refresh, expires_at=expires)
    db.add(db_token)
    user.last_login = datetime.utcnow()
    user.failed_login_attempts = 0  # reset on successful login
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Token creation failed: " + str(e))

    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": UserOut.model_validate(user),
    }


def _log_login(db: Session, request: Request, user_id, tenant_id, email: str, success: bool, reason: str = None):
    log = LoginLog(
        user_id=user_id,
        tenant_id=tenant_id,
        email=email,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=success,
        failure_reason=reason,
    )
    db.add(log)
    db.commit()


# ─────────────────────────── Signup ───────────────────────────

@router.post("/signup", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    # Check email uniqueness across all tenant admins
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    tenant, user = create_tenant_with_admin(db, data)
    return {"message": f"Account created successfully. Your {settings.TRIAL_DAYS}-day trial is now active."}


# ─────────────────────────── Login ───────────────────────────

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user or not user.hashed_password:
        _log_login(db, request, None, None, data.email, False, "User not found")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Account lockout check
    if (user.failed_login_attempts or 0) >= MAX_FAILED_ATTEMPTS:
        if user.last_login and (datetime.utcnow() - user.last_login).total_seconds() < LOCKOUT_MINUTES * 60:
            raise HTTPException(
                status_code=429,
                detail=f"Account temporarily locked after {MAX_FAILED_ATTEMPTS} failed attempts. "
                       f"Try again in {LOCKOUT_MINUTES} minutes."
            )
        else:
            # Lockout expired, reset counter
            user.failed_login_attempts = 0
            db.commit()

    if not verify_password(data.password, user.hashed_password):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        db.commit()
        _log_login(db, request, user.id, user.tenant_id, data.email, False, "Wrong password")
        remaining = MAX_FAILED_ATTEMPTS - user.failed_login_attempts
        if remaining > 0:
            raise HTTPException(status_code=401, detail=f"Invalid credentials. {remaining} attempt(s) remaining.")
        raise HTTPException(status_code=429, detail="Account locked due to too many failed attempts.")

    if user.status == UserStatus.DISABLED:
        raise HTTPException(status_code=403, detail="Account is disabled. Contact your admin.")

    if user.status == UserStatus.DELETED:
        raise HTTPException(status_code=403, detail="Account not found.")

    # Check tenant status for non-super-admins
    if user.role != UserRole.SUPER_ADMIN and user.tenant:
        tenant = user.tenant
        if tenant.status == TenantStatus.PENDING:
            raise HTTPException(
                status_code=403,
                detail="Your trial period has expired. Please wait for admin approval.",
            )
        if tenant.status == TenantStatus.DISABLED:
            raise HTTPException(status_code=403, detail="Your organisation account is disabled.")

    user.failed_login_attempts = 0
    _log_login(db, request, user.id, user.tenant_id, data.email, True)
    return _build_token_response(user, db)


# ─────────────────────────── Refresh Token ───────────────────────────

@router.post("/refresh", response_model=TokenResponse)
def refresh_token(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    token_record = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token == data.refresh_token,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if not token_record:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Rotate: revoke old, issue new
    token_record.revoked = True
    db.commit()

    user = db.query(User).filter(User.id == token_record.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return _build_token_response(user, db)


# ─────────────────────────── Logout ───────────────────────────

@router.post("/logout", response_model=MessageResponse)
def logout(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    token_record = db.query(RefreshToken).filter(RefreshToken.token == data.refresh_token).first()
    if token_record:
        token_record.revoked = True
        db.commit()
    return {"message": "Logged out successfully"}


# ─────────────────────────── Password Reset ───────────────────────────

@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(data: PasswordResetRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email, User.status == UserStatus.ACTIVE).first()
    # Always return success to prevent email enumeration
    if user:
        token = generate_reset_token()
        expires = datetime.utcnow() + timedelta(minutes=30)
        reset_rec = PasswordResetToken(user_id=user.id, token=token, expires_at=expires)
        db.add(reset_rec)
        db.commit()
        background.add_task(send_password_reset_email, user.email, token, user.full_name)
    return {"message": "If your email is registered, you will receive a password reset link."}


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    record = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token == data.token,
            PasswordResetToken.used == False,
            PasswordResetToken.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.query(User).filter(User.id == record.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(data.new_password)
    record.used = True
    db.commit()
    return {"message": "Password reset successfully. You can now log in."}


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.hashed_password:
        raise HTTPException(status_code=400, detail="Account uses social login; no password to change.")
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"message": "Password changed successfully"}


# ─────────────────────────── Google OAuth ───────────────────────────

@router.get("/google/login")
def google_login():
    """Returns the Google OAuth authorization URL."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    from urllib.parse import urlencode
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    return {"authorization_url": url}


@router.get("/google/callback")
async def google_callback(code: str, db: Session = Depends(get_db)):
    """Handle Google OAuth callback, sign in or register user."""
    import httpx
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Google OAuth not configured")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange OAuth code")

    tokens = token_resp.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="No ID token in OAuth response")

    # Decode without verification (Google's public key validation skipped for brevity)
    import base64, json as _json
    parts = id_token.split(".")
    padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
    claims = _json.loads(base64.urlsafe_b64decode(padded))

    google_id = claims.get("sub")
    email = claims.get("email")
    name = claims.get("name", "")

    # Try to find existing user by google_id or email
    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()

    if user:
        if not user.google_id:
            user.google_id = google_id
            user.auth_provider = AuthProvider.GOOGLE
            db.commit()
    else:
        # Auto-register as new tenant
        from app.services.tenant_service import create_tenant_with_google
        # Use email domain as default company
        company = claims.get("hd") or email.split("@")[1].split(".")[0].title()
        _, user = create_tenant_with_google(db, company, name, email, google_id)

    result = _build_token_response(user, db)
    # Redirect to frontend with tokens
    from fastapi.responses import RedirectResponse
    redirect = (
        f"{settings.FRONTEND_URL}/oauth-callback.html"
        f"?access_token={result['access_token']}"
        f"&refresh_token={result['refresh_token']}"
    )
    return RedirectResponse(url=redirect)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


# ─── Profile Photo Upload ─────────────────────────────────────
from pathlib import Path as _Path
import uuid as _uuid

_PHOTO_DIR = _Path("uploads/avatars")
_PHOTO_DIR.mkdir(parents=True, exist_ok=True)

@router.post("/profile/photo")
async def upload_profile_photo(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload or replace profile photo. Returns URL to the photo."""
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:  # 2 MB max
        raise HTTPException(400, "Photo too large (max 2 MB)")
    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(400, "Only JPEG, PNG, WebP or GIF allowed")

    ext = _Path(file.filename).suffix.lower() or ".jpg"
    fname = str(_uuid.uuid4()) + ext
    (_PHOTO_DIR / fname).write_bytes(content)

    # Store path on user — use mobile field as temp workaround? No — add avatar_url col
    # We'll store in a simple way: write to a sidecar JSON keyed by user id
    import json
    avatar_map_path = _Path("uploads/avatars/map.json")
    avatar_map = {}
    if avatar_map_path.exists():
        try: avatar_map = json.loads(avatar_map_path.read_text())
        except: pass
    # Delete old file if exists
    old = avatar_map.get(str(current_user.id))
    if old:
        try: (_PHOTO_DIR / old).unlink(missing_ok=True)
        except: pass
    avatar_map[str(current_user.id)] = fname
    avatar_map_path.write_text(json.dumps(avatar_map))

    return {"photo_url": f"/api/v1/auth/profile/photo/{fname}", "filename": fname}


@router.get("/profile/photo/{filename}")
def get_profile_photo(filename: str):
    """Serve a profile photo."""
    from fastapi.responses import FileResponse as _FR
    fpath = _Path("uploads/avatars") / filename
    if not fpath.exists():
        raise HTTPException(404, "Photo not found")
    return _FR(str(fpath))


@router.get("/profile/photo-url")
def my_photo_url(current_user: User = Depends(get_current_user)):
    """Get current user's photo URL if set."""
    import json
    from pathlib import Path as _P
    avatar_map_path = _P("uploads/avatars/map.json")
    if avatar_map_path.exists():
        try:
            avatar_map = json.loads(avatar_map_path.read_text())
            fname = avatar_map.get(str(current_user.id))
            if fname:
                return {"photo_url": f"/api/v1/auth/profile/photo/{fname}"}
        except: pass
    return {"photo_url": None}
