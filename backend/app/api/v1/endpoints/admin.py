from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.auth.dependencies import get_super_admin
from app.database import get_db
from app.models import (
    Tenant, TenantStatus, User, UserRole, UserStatus, TenantSubscription, PricingPlan, PDCNClaim,
    LoginLog, ActivityLog,
)
from app.schemas import (
    TenantOut, TenantListResponse, TenantStatusUpdate, TenantExtendTrial,
    SuperAdminDashboard, UserOut, UserListResponse, MessageResponse,
    LoginLogOut, ActivityLogOut,
)

router = APIRouter(prefix="/admin", tags=["Super Admin"])


def _enrich_tenant(tenant: Tenant, db: Session) -> dict:
    user_count = db.query(User).filter(
        User.tenant_id == tenant.id, User.status != UserStatus.DELETED
    ).count()
    # Get admin email
    admin_user = db.query(User).filter(
        User.tenant_id == tenant.id,
        User.role == "tenant_admin",
        User.status != UserStatus.DELETED,
    ).first()
    # Get active plan name
    from app.models import TenantSubscription, PricingPlan
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant.id,
        TenantSubscription.is_active == True,
    ).first()
    plan_name = None
    if sub:
        plan = db.query(PricingPlan).filter(PricingPlan.id == sub.plan_id).first()
        plan_name = plan.name if plan else None
    days_remaining = None
    if tenant.trial_end and tenant.status == TenantStatus.TRIAL:
        delta = (tenant.trial_end - datetime.utcnow()).days
        days_remaining = max(0, delta)
    d = TenantOut.model_validate(tenant).model_dump()
    d["user_count"] = user_count
    d["admin_email"] = admin_user.email if admin_user else "—"
    d["plan_name"] = plan_name or "No plan"
    d["trial_days_remaining"] = days_remaining
    return d


# ─────────────────────────── Dashboard ───────────────────────────

@router.get("/dashboard", response_model=SuperAdminDashboard)
def dashboard(admin=Depends(get_super_admin), db: Session = Depends(get_db)):
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0)

    total = db.query(Tenant).filter(Tenant.status != TenantStatus.DELETED).count()
    active = db.query(Tenant).filter(Tenant.status == TenantStatus.ACTIVE).count()
    trial = db.query(Tenant).filter(Tenant.status == TenantStatus.TRIAL).count()
    pending = db.query(Tenant).filter(Tenant.status == TenantStatus.PENDING).count()
    disabled = db.query(Tenant).filter(Tenant.status == TenantStatus.DISABLED).count()
    total_users = db.query(User).filter(
        User.role != UserRole.SUPER_ADMIN, User.status != UserStatus.DELETED
    ).count()
    new_this_month = db.query(Tenant).filter(Tenant.created_at >= month_start).count()
    recent_logins = db.query(LoginLog).filter(LoginLog.created_at >= month_start, LoginLog.success == True).count()

    return {
        "total_tenants": total,
        "active_tenants": active,
        "trial_tenants": trial,
        "pending_tenants": pending,
        "disabled_tenants": disabled,
        "total_users": total_users,
        "new_tenants_this_month": new_this_month,
        "recent_logins": recent_logins,
    }


# ─────────────────────────── Tenant Management ───────────────────────────

@router.get("/tenants", response_model=TenantListResponse)
def list_tenants(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[TenantStatus] = None,
    search: Optional[str] = None,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Tenant).filter(Tenant.status != TenantStatus.DELETED)
    if status:
        q = q.filter(Tenant.status == status)
    if search:
        q = q.filter(Tenant.company_name.ilike(f"%{search}%"))
    total = q.count()
    tenants = q.order_by(Tenant.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "tenants": [_enrich_tenant(t, db) for t in tenants],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
def get_tenant(tenant_id: str, admin=Depends(get_super_admin), db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _enrich_tenant(tenant, db)


@router.patch("/tenants/{tenant_id}/status", response_model=MessageResponse)
def update_tenant_status(
    tenant_id: str,
    data: TenantStatusUpdate,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.status = data.status
    db.commit()
    return {"message": f"Tenant status updated to {data.status}"}


@router.post("/tenants/{tenant_id}/approve", response_model=MessageResponse)
def approve_tenant(tenant_id: str, admin=Depends(get_super_admin), db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.status = TenantStatus.ACTIVE
    db.commit()
    return {"message": "Tenant approved and set to Active"}


@router.post("/tenants/{tenant_id}/extend-trial", response_model=MessageResponse)
def extend_trial(
    tenant_id: str,
    data: TenantExtendTrial,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    base = max(tenant.trial_end or datetime.utcnow(), datetime.utcnow())
    tenant.trial_end = base + timedelta(days=data.days)
    tenant.status = TenantStatus.TRIAL
    db.commit()
    return {"message": f"Trial extended by {data.days} days"}


@router.delete("/tenants/{tenant_id}", response_model=MessageResponse)
def delete_tenant(tenant_id: str, admin=Depends(get_super_admin), db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant.status = TenantStatus.DELETED
    db.commit()
    return {"message": "Tenant deleted (soft delete)"}


# ─────────────────────────── Users (platform-wide) ───────────────────────────

@router.get("/users")
def list_all_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    per_page_max: int = Query(500, include_in_schema=False),
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    # Allow large fetch for client-side filtering (max 500)
    effective_per_page = min(per_page, 500)
    q = db.query(User).filter(User.role != UserRole.SUPER_ADMIN, User.status != UserStatus.DELETED)
    total = q.count()
    users = q.order_by(User.created_at.desc()).offset((page - 1) * effective_per_page).limit(effective_per_page).all()

    # Batch fetch tenants for tenant_name
    tenant_ids = list({u.tenant_id for u in users if u.tenant_id})
    tenants = {t.id: t for t in db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).all()} if tenant_ids else {}

    result = []
    for u in users:
        d = UserOut.model_validate(u).model_dump()
        d["id"] = str(d["id"])
        d["tenant_id"] = str(d["tenant_id"]) if d["tenant_id"] else None
        d["tenant_name"] = tenants[u.tenant_id].company_name if u.tenant_id and u.tenant_id in tenants else "—"
        d["last_login_at"] = u.last_login.isoformat() if u.last_login else None
        result.append(d)

    return {"users": result, "total": total, "page": page, "per_page": effective_per_page}


# ─────────────────────────── Logs ───────────────────────────

@router.get("/logs/login")
def login_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    q = db.query(LoginLog).order_by(LoginLog.created_at.desc())
    total = q.count()
    logs = q.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "logs": [LoginLogOut.model_validate(l) for l in logs],
        "total": total, "page": page, "per_page": per_page,
    }


@router.get("/logs/activity")
def activity_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    q = db.query(ActivityLog).order_by(ActivityLog.created_at.desc())
    total = q.count()
    logs = q.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "logs": [{"id": str(l.id), "action": l.action, "resource": l.resource,
                  "details": l.details, "ip_address": l.ip_address,
                  "created_at": l.created_at.isoformat()} for l in logs],
        "total": total, "page": page, "per_page": per_page,
    }


# ─────────────────────────── Tenant User Control ───────────────────────────

@router.get("/tenants/{tenant_id}/detail")
def tenant_detail(
    tenant_id: str,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Full tenant detail: info + users + subscription + plan limits."""
    from app.models import TenantSubscription, PricingPlan
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    # Users (non-deleted)
    users = db.query(User).filter(
        User.tenant_id == tenant.id,
        User.status != UserStatus.DELETED,
    ).order_by(User.created_at).all()

    # Subscription + plan
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant.id
    ).first()
    plan = db.query(PricingPlan).filter(
        PricingPlan.id == sub.plan_id
    ).first() if sub else None

    tenant_data = _enrich_tenant(tenant, db)
    tenant_data["subscription"] = {
        "id": str(sub.id) if sub else None,
        "plan_id": str(sub.plan_id) if sub else None,
        "plan_name": plan.name if plan else None,
        "billing_cycle": sub.billing_cycle if sub else None,
        "claims_used": sub.claims_used if sub else 0,
        "max_claims": plan.max_claims_per_month if plan else None,
        "max_users": plan.max_users if plan else None,
        "expires_at": sub.expires_at.isoformat() if sub and sub.expires_at else None,
        "is_active": sub.is_active if sub else False,
    } if sub else None

    tenant_data["users"] = [{
        "id": str(u.id),
        "full_name": u.full_name,
        "email": u.email,
        "role": u.role,
        "status": u.status,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "created_at": u.created_at.isoformat(),
    } for u in users]

    return tenant_data


@router.post("/tenants/{tenant_id}/activate", response_model=MessageResponse)
def activate_tenant(
    tenant_id: str,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Set tenant to Active and enable all their users."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    tenant.status = TenantStatus.ACTIVE
    # Re-enable all disabled users (those that were auto-disabled on trial expiry)
    db.query(User).filter(
        User.tenant_id == tenant.id,
        User.status == UserStatus.DISABLED,
    ).update({"status": UserStatus.ACTIVE}, synchronize_session=False)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "Activation failed: " + str(e))
    return {"message": "Tenant activated. All users re-enabled."}


@router.post("/tenants/{tenant_id}/suspend", response_model=MessageResponse)
def suspend_tenant(
    tenant_id: str,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Suspend tenant and disable all their non-admin users."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    tenant.status = TenantStatus.DISABLED
    db.query(User).filter(
        User.tenant_id == tenant.id,
        User.role != UserRole.TENANT_ADMIN,
    ).update({"status": UserStatus.DISABLED}, synchronize_session=False)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "Suspension failed: " + str(e))
    return {"message": "Tenant suspended. Non-admin users disabled."}


@router.patch("/tenants/{tenant_id}/users/{user_id}/status", response_model=MessageResponse)
def toggle_tenant_user_status(
    tenant_id: str,
    user_id: str,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Toggle individual tenant user between active/disabled.
    Also enforces plan user limit — cannot enable if at limit."""
    from app.models import TenantSubscription, PricingPlan
    user = db.query(User).filter(
        User.id == user_id, User.tenant_id == tenant_id
    ).first()
    if not user:
        raise HTTPException(404, "User not found in this tenant")

    if user.status == UserStatus.ACTIVE:
        # Disable
        user.status = UserStatus.DISABLED
        msg = f"{user.full_name} disabled."
    else:
        # Check plan user limit before enabling
        sub = db.query(TenantSubscription).filter(
            TenantSubscription.tenant_id == tenant_id
        ).first()
        if sub:
            plan = db.query(PricingPlan).filter(PricingPlan.id == sub.plan_id).first()
            if plan and plan.max_users:
                active_count = db.query(User).filter(
                    User.tenant_id == tenant_id,
                    User.status == UserStatus.ACTIVE,
                    User.role != UserRole.SUPER_ADMIN,
                ).count()
                if active_count >= plan.max_users:
                    raise HTTPException(
                        400,
                        f"Plan limit reached: {plan.name} allows max {plan.max_users} users. "
                        f"Currently {active_count} active. Upgrade plan or disable another user first."
                    )
        user.status = UserStatus.ACTIVE
        msg = f"{user.full_name} enabled."
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    return {"message": msg}


@router.post("/tenants/{tenant_id}/assign-plan", response_model=MessageResponse)
def assign_tenant_plan(
    tenant_id: str,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
    plan_id: str = None,
    billing_cycle: str = "monthly",
):
    """Assign or change a tenant's pricing plan. Enforces user count vs plan limit."""
    from app.models import TenantSubscription, PricingPlan
    from pydantic import BaseModel as _BM
    # Accept body via query params for simplicity (body version below)
    raise HTTPException(400, "Use POST body version")


from pydantic import BaseModel as _PBM

class AssignPlanToTenant(_PBM):
    plan_id: str
    billing_cycle: str = "monthly"


@router.post("/tenants/{tenant_id}/plan", response_model=MessageResponse)
def assign_plan_to_tenant(
    tenant_id: str,
    body: AssignPlanToTenant,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Assign or upgrade a tenant's plan. Auto-disables excess users if new plan has lower user limit."""
    from app.models import TenantSubscription, PricingPlan

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    plan = db.query(PricingPlan).filter(PricingPlan.id == body.plan_id, PricingPlan.is_active == True).first()
    if not plan:
        raise HTTPException(404, "Plan not found or inactive")

    # Check if downgrade would violate user count
    active_users = db.query(User).filter(
        User.tenant_id == tenant_id,
        User.status == UserStatus.ACTIVE,
        User.role != UserRole.SUPER_ADMIN,
    ).count()

    warning = None
    if plan.max_users and active_users > plan.max_users:
        # Auto-disable excess non-admin users (keep tenant_admin active)
        excess_users = db.query(User).filter(
            User.tenant_id == tenant_id,
            User.status == UserStatus.ACTIVE,
            User.role != UserRole.TENANT_ADMIN,
            User.role != UserRole.SUPER_ADMIN,
        ).order_by(User.created_at.desc()).limit(active_users - plan.max_users).all()
        for u in excess_users:
            u.status = UserStatus.DISABLED
        warning = f"{len(excess_users)} users disabled to fit new plan limit of {plan.max_users}."

    # Upsert subscription
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).first()
    if sub:
        sub.plan_id = plan.id
        sub.billing_cycle = body.billing_cycle
        sub.claims_used = 0
        sub.is_active = True
        sub.updated_at = datetime.utcnow()
    else:
        sub = TenantSubscription(
            tenant_id=tenant_id,
            plan_id=plan.id,
            billing_cycle=body.billing_cycle,
            is_active=True,
        )
        db.add(sub)

    # Activate tenant if pending/trial
    if tenant.status in (TenantStatus.PENDING, TenantStatus.TRIAL):
        tenant.status = TenantStatus.ACTIVE

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "Plan assignment failed: " + str(e))

    msg = f"Plan '{plan.name}' assigned successfully."
    if warning:
        msg += " " + warning
    return {"message": msg}


@router.get("/tenants/{tenant_id}/plan-limits")
def check_plan_limits(
    tenant_id: str,
    admin=Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Get current usage vs plan limits for a tenant."""
    from app.models import TenantSubscription, PricingPlan, PDCNClaim
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == tenant_id
    ).first()
    plan = db.query(PricingPlan).filter(PricingPlan.id == sub.plan_id).first() if sub else None

    active_users = db.query(User).filter(
        User.tenant_id == tenant_id,
        User.status == UserStatus.ACTIVE,
    ).count()
    total_users = db.query(User).filter(
        User.tenant_id == tenant_id,
        User.status != UserStatus.DELETED,
    ).count()
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    claims_this_month = db.query(PDCNClaim).filter(
        PDCNClaim.tenant_id == tenant_id,
        PDCNClaim.created_at >= month_start,
    ).count()

    return {
        "plan": {"id": str(plan.id), "name": plan.name, "slug": plan.slug} if plan else None,
        "billing_cycle": sub.billing_cycle if sub else None,
        "limits": {
            "max_users": plan.max_users if plan else None,
            "max_claims": plan.max_claims_per_month if plan else None,
            "max_storage_gb": plan.max_storage_gb if plan else 5,
        },
        "usage": {
            "active_users": active_users,
            "total_users": total_users,
            "claims_this_month": claims_this_month,
            "claims_used_sub": sub.claims_used if sub else 0,
        },
        "over_limit": {
            "users": plan.max_users is not None and active_users > plan.max_users if plan else False,
            "claims": plan.max_claims_per_month is not None and claims_this_month > plan.max_claims_per_month if plan else False,
        }
    }
