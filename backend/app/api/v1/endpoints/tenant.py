from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_tenant_admin, get_active_tenant_user
from app.auth.security import hash_password
from app.database import get_db
from app.models import User, UserRole, UserStatus, ActivityLog
from app.schemas import (
    UserCreate, UserUpdate, UserOut, UserListResponse,
    UserStatusUpdate, AdminResetPassword, MessageResponse,
    TenantDashboard,
)

router = APIRouter(prefix="/tenant", tags=["Tenant"])


def _log_activity(db, request, user, action, resource=None, resource_id=None, details=None):
    try:
        log = ActivityLog(
            user_id=user.id, tenant_id=user.tenant_id, action=action,
            resource=resource, resource_id=resource_id, details=details,
            ip_address=request.client.host if request.client else None,
        )
        db.add(log)
        db.commit()
    except Exception:
        pass


SINGLETON_ROLES = {UserRole.CN_TEAM, UserRole.FINANCE_TEAM, UserRole.CFA_TEAM, UserRole.FINANCE_CFA_TEAM}


def _derive_role(is_finance: bool, is_cfa: bool, requested_role) -> str:
    if is_finance and is_cfa:
        return UserRole.FINANCE_CFA_TEAM
    if is_finance:
        return UserRole.FINANCE_TEAM
    if is_cfa:
        return UserRole.CFA_TEAM
    return requested_role


def _check_singleton_limit(db, tenant_id, role, exclude_user_id=None):
    if role not in SINGLETON_ROLES:
        return
    if role == UserRole.FINANCE_CFA_TEAM:
        roles_to_check = [UserRole.FINANCE_TEAM, UserRole.CFA_TEAM, UserRole.FINANCE_CFA_TEAM]
        label = "Finance/CFA Team"
    elif role == UserRole.FINANCE_TEAM:
        roles_to_check = [UserRole.FINANCE_TEAM, UserRole.FINANCE_CFA_TEAM]
        label = "Finance Team"
    elif role == UserRole.CFA_TEAM:
        roles_to_check = [UserRole.CFA_TEAM, UserRole.FINANCE_CFA_TEAM]
        label = "CFA Team"
    else:
        roles_to_check = [UserRole.CN_TEAM]
        label = "CN Team"

    q = db.query(User).filter(
        User.tenant_id == tenant_id,
        User.status != UserStatus.DELETED,
        User.role.in_(roles_to_check),
    )
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    existing = q.first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="A " + label + " user (" + existing.full_name + ") already exists. Only one " + label + " user is allowed per organisation."
        )


# ─── Dashboard ───────────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=TenantDashboard)
def tenant_dashboard(current_user: User = Depends(get_active_tenant_user), db: Session = Depends(get_db)):
    from datetime import timedelta
    tid = current_user.tenant_id
    users_q = db.query(User).filter(User.tenant_id == tid, User.status != UserStatus.DELETED)
    total    = users_q.count()
    active   = users_q.filter(User.status == UserStatus.ACTIVE).count()
    disabled = users_q.filter(User.status == UserStatus.DISABLED).count()
    since    = datetime.utcnow() - timedelta(days=7)
    recent   = db.query(ActivityLog).filter(ActivityLog.tenant_id == tid, ActivityLog.created_at >= since).count()
    return {"total_users": total, "active_users": active, "disabled_users": disabled, "recent_activity": recent}


# ─── Role Slots ──────────────────────────────────────────────────────────────

@router.get("/users/role-slots")
def get_role_slots(current_user: User = Depends(get_tenant_admin), db: Session = Depends(get_db)):
    tid = current_user.tenant_id

    def slot(roles):
        u = db.query(User).filter(
            User.tenant_id == tid,
            User.status != UserStatus.DELETED,
            User.role.in_(roles)
        ).first()
        if not u:
            return None
        return {"id": str(u.id), "name": u.full_name, "email": u.email, "role": u.role}

    return {
        "cn_team":      slot([UserRole.CN_TEAM]),
        "finance_team": slot([UserRole.FINANCE_TEAM, UserRole.FINANCE_CFA_TEAM]),
        "cfa_team":     slot([UserRole.CFA_TEAM, UserRole.FINANCE_CFA_TEAM]),
    }


# ─── List Users ──────────────────────────────────────────────────────────────

@router.get("/users", response_model=UserListResponse)
def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[UserStatus] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_tenant_admin),
    db: Session = Depends(get_db),
):
    q = db.query(User).filter(
        User.tenant_id == current_user.tenant_id,
        User.status != UserStatus.DELETED,
        User.role != UserRole.SUPER_ADMIN,
    )
    if status:
        q = q.filter(User.status == status)
    if search:
        q = q.filter((User.full_name.ilike("%" + search + "%")) | (User.email.ilike("%" + search + "%")))
    total = q.count()
    users = q.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"users": users, "total": total, "page": page, "per_page": per_page}


# ─── Create User ─────────────────────────────────────────────────────────────

@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserCreate,
    request: Request,
    current_user: User = Depends(get_tenant_admin),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(
        User.email == data.email,
        User.tenant_id == current_user.tenant_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists in this organisation")

    final_role = _derive_role(data.is_finance_team, data.is_cfa_team, data.role)
    _check_singleton_limit(db, current_user.tenant_id, final_role)

    try:
        user = User(
            tenant_id=current_user.tenant_id,
            full_name=data.full_name,
            email=data.email,
            mobile=data.mobile,
            hashed_password=hash_password(data.password),
            role=final_role,
            is_finance_team=(final_role in (UserRole.FINANCE_TEAM, UserRole.FINANCE_CFA_TEAM)),
            is_cfa_team=(final_role in (UserRole.CFA_TEAM, UserRole.FINANCE_CFA_TEAM)),
            status=UserStatus.ACTIVE,
            # Dealer-specific fields
            dealer_series=data.dealer_series if final_role == UserRole.DEALER else None,
            sap_code=data.sap_code if final_role == UserRole.DEALER else None,
            business_group=data.business_group if final_role == UserRole.DEALER else None,
            region=data.region if final_role == UserRole.DEALER else None,
            city=data.city if final_role == UserRole.DEALER else None,
            state=data.state if final_role == UserRole.DEALER else None,
            credit_check=data.credit_check if final_role == UserRole.DEALER else None,
            distributor_name=data.distributor_name or data.full_name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="DB error: " + str(e))

    _log_activity(db, request, current_user, "CREATE_USER", "user", str(user.id), "Created " + user.email + " as " + str(final_role))
    return user


# ─── Get User ────────────────────────────────────────────────────────────────

@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: str, current_user: User = Depends(get_tenant_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id,
        User.status != UserStatus.DELETED
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ─── Update User ─────────────────────────────────────────────────────────────

@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    data: UserUpdate,
    request: Request,
    current_user: User = Depends(get_tenant_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id,
        User.status != UserStatus.DELETED
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    upd = data.model_dump(exclude_none=True)
    new_finance  = upd.get("is_finance_team", user.is_finance_team)
    new_cfa      = upd.get("is_cfa_team", user.is_cfa_team)
    new_role_raw = upd.get("role", user.role)
    final_role   = _derive_role(new_finance, new_cfa, new_role_raw)

    if final_role != user.role:
        _check_singleton_limit(db, current_user.tenant_id, final_role, exclude_user_id=user_id)

    upd["role"]           = final_role
    upd["is_finance_team"] = (final_role in (UserRole.FINANCE_TEAM, UserRole.FINANCE_CFA_TEAM))
    upd["is_cfa_team"]     = (final_role in (UserRole.CFA_TEAM, UserRole.FINANCE_CFA_TEAM))

    for field, val in upd.items():
        setattr(user, field, val)
    db.commit()
    db.refresh(user)
    _log_activity(db, request, current_user, "UPDATE_USER", "user", str(user.id), "Updated " + user.email)
    return user


# ─── Update User Status ───────────────────────────────────────────────────────

@router.patch("/users/{user_id}/status", response_model=MessageResponse)
def update_user_status(
    user_id: str,
    data: UserStatusUpdate,
    request: Request,
    current_user: User = Depends(get_tenant_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id,
        User.status != UserStatus.DELETED
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot change your own status")
    if data.status == UserStatus.DELETED:
        user.deleted_at = datetime.utcnow()
    user.status = data.status
    db.commit()
    _log_activity(db, request, current_user, "UPDATE_USER_STATUS", "user", str(user.id), "Set status to " + str(data.status))
    return {"message": "User status updated to " + str(data.status)}


# ─── Delete User ─────────────────────────────────────────────────────────────

@router.delete("/users/{user_id}", response_model=MessageResponse)
def delete_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(get_tenant_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id,
        User.status != UserStatus.DELETED
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user.status = UserStatus.DELETED
    user.deleted_at = datetime.utcnow()
    db.commit()
    _log_activity(db, request, current_user, "DELETE_USER", "user", str(user.id), "Deleted " + user.email)
    return {"message": "User deleted"}


# ─── Reset Password ───────────────────────────────────────────────────────────

@router.post("/users/{user_id}/reset-password", response_model=MessageResponse)
def admin_reset_password(
    user_id: str,
    data: AdminResetPassword,
    request: Request,
    current_user: User = Depends(get_tenant_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.id == user_id,
        User.tenant_id == current_user.tenant_id,
        User.status == UserStatus.ACTIVE
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(data.new_password)
    db.commit()
    _log_activity(db, request, current_user, "RESET_USER_PASSWORD", "user", str(user.id), None)
    return {"message": "Password reset successfully"}


# ─── Profile ─────────────────────────────────────────────────────────────────

@router.get("/profile", response_model=UserOut)
def my_profile(current_user: User = Depends(get_active_tenant_user)):
    return current_user


# ── Update own profile (name, mobile) ──────────────────────────
from pydantic import BaseModel as _BM
class ProfileUpdate(_BM):
    full_name: str = None
    mobile: str = None

@router.patch("/profile", response_model=UserOut)
def update_own_profile(
    body: ProfileUpdate,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    """Update own profile (name, mobile)."""
    if body.full_name and body.full_name.strip():
        current_user.full_name = body.full_name.strip()
    if body.mobile is not None:
        current_user.mobile = body.mobile.strip() if body.mobile and body.mobile.strip() else None
    try:
        db.commit()
        db.refresh(current_user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update profile: " + str(e))
    return current_user
