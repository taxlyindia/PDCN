"""
Pricing Plan API — Super Admin can CRUD plans.
Public endpoint returns active plans for landing page.
"""
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_active_tenant_user
from app.database import get_db
from app.models import PricingPlan, TenantSubscription, User, UserRole, PDCNClaim, Tenant

router = APIRouter(prefix="/pricing", tags=["Pricing"])


def plan_dict(p: PricingPlan) -> dict:
    annual_monthly_equiv = round(p.annual_price / 12) if p.annual_price else 0
    return {
        "id": str(p.id),
        "name": p.name,
        "slug": p.slug,
        "description": p.description,
        "monthly_price": p.monthly_price,
        "annual_price": p.annual_price,
        "annual_monthly_equiv": annual_monthly_equiv,
        "annual_discount_pct": p.annual_discount_pct,
        "max_users": p.max_users,
        "max_claims_per_month": p.max_claims_per_month,
        "max_storage_gb": p.max_storage_gb,
        "features": json.loads(p.features) if p.features else [],
        "is_active": p.is_active,
        "is_featured": p.is_featured,
        "sort_order": p.sort_order,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


# ── Public: get all active plans (no auth needed) ─────────────
@router.get("/plans/public")
def get_public_plans(db: Session = Depends(get_db)):
    plans = db.query(PricingPlan).filter(
        PricingPlan.is_active == True
    ).order_by(PricingPlan.sort_order).all()
    return [plan_dict(p) for p in plans]


# ── Admin: list all plans ──────────────────────────────────────
@router.get("/plans")
def list_plans(
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    plans = db.query(PricingPlan).order_by(PricingPlan.sort_order).all()
    return [plan_dict(p) for p in plans]


# ── Admin: create / update plan ────────────────────────────────
class PlanBody(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    monthly_price: int = 0
    annual_price: int = 0
    annual_discount_pct: int = 0
    max_users: Optional[int] = None
    max_claims_per_month: Optional[int] = None
    max_storage_gb: int = 5
    features: list = []
    is_active: bool = True
    is_featured: bool = False
    sort_order: int = 0


@router.post("/plans", status_code=201)
def create_plan(
    body: PlanBody,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    existing = db.query(PricingPlan).filter(PricingPlan.slug == body.slug).first()
    if existing:
        raise HTTPException(400, f"Plan with slug '{body.slug}' already exists")
    plan = PricingPlan(
        name=body.name, slug=body.slug, description=body.description,
        monthly_price=body.monthly_price, annual_price=body.annual_price,
        annual_discount_pct=body.annual_discount_pct,
        max_users=body.max_users, max_claims_per_month=body.max_claims_per_month,
        max_storage_gb=body.max_storage_gb,
        features=json.dumps(body.features),
        is_active=body.is_active, is_featured=body.is_featured,
        sort_order=body.sort_order, updated_by=current_user.id,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan_dict(plan)


@router.patch("/plans/{plan_id}")
def update_plan(
    plan_id: str,
    body: PlanBody,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    plan = db.query(PricingPlan).filter(PricingPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    plan.name = body.name
    plan.slug = body.slug
    plan.description = body.description
    plan.monthly_price = body.monthly_price
    plan.annual_price = body.annual_price
    plan.annual_discount_pct = body.annual_discount_pct
    plan.max_users = body.max_users
    plan.max_claims_per_month = body.max_claims_per_month
    plan.max_storage_gb = body.max_storage_gb
    plan.features = json.dumps(body.features)
    plan.is_active = body.is_active
    plan.is_featured = body.is_featured
    plan.sort_order = body.sort_order
    plan.updated_by = current_user.id
    plan.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(plan)
    return plan_dict(plan)


@router.delete("/plans/{plan_id}")
def delete_plan(
    plan_id: str,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    plan = db.query(PricingPlan).filter(PricingPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    plan.is_active = False
    db.commit()
    return {"message": "Plan deactivated"}


# ── Tenant subscription management ────────────────────────────
@router.get("/subscriptions")
def list_subscriptions(
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    # Use a single JOIN query instead of N+1
    from sqlalchemy.orm import joinedload
    subs = db.query(TenantSubscription).all()
    if not subs:
        return []
    # Batch fetch tenants and plans
    tenant_ids = list({s.tenant_id for s in subs})
    plan_ids   = list({s.plan_id   for s in subs})
    tenants = {t.id: t for t in db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).all()}
    plans   = {p.id: p for p in db.query(PricingPlan).filter(PricingPlan.id.in_(plan_ids)).all()}
    result = []
    for s in subs:
        tenant = tenants.get(s.tenant_id)
        plan   = plans.get(s.plan_id)
        result.append({
            "id": str(s.id),
            "tenant_id": str(s.tenant_id),
            "tenant_name": tenant.company_name if tenant else "—",
            "plan_name": plan.name if plan else "—",
            "plan_slug": plan.slug if plan else "—",
            "billing_cycle": s.billing_cycle,
            "claims_used": s.claims_used,
            "max_claims": plan.max_claims_per_month if plan else None,
            "max_users": plan.max_users if plan else None,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "is_active": s.is_active,
        })
    return result


class AssignPlanBody(BaseModel):
    tenant_id: str
    plan_id: str
    billing_cycle: str = "monthly"


@router.post("/subscriptions/assign")
def assign_plan(
    body: AssignPlanBody,
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "Super Admin only")
    plan = db.query(PricingPlan).filter(PricingPlan.id == body.plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == body.tenant_id
    ).first()
    if sub:
        sub.plan_id = body.plan_id
        sub.billing_cycle = body.billing_cycle
        sub.claims_used = 0
        sub.updated_at = datetime.utcnow()
    else:
        sub = TenantSubscription(
            tenant_id=body.tenant_id,
            plan_id=body.plan_id,
            billing_cycle=body.billing_cycle,
        )
        db.add(sub)
    db.commit()
    return {"message": "Plan assigned successfully"}


# ── Tenant: check own plan limits ─────────────────────────────
@router.get("/my-plan")
def my_plan(
    current_user: User = Depends(get_active_tenant_user),
    db: Session = Depends(get_db),
):
    sub = db.query(TenantSubscription).filter(
        TenantSubscription.tenant_id == current_user.tenant_id
    ).first()
    if not sub:
        return {"plan": None, "limits": {"max_users": None, "max_claims": None}}
    plan = db.query(PricingPlan).filter(PricingPlan.id == sub.plan_id).first()

    # Count current users
    from app.models import UserStatus
    user_count = db.query(User).filter(
        User.tenant_id == current_user.tenant_id,
        User.status == UserStatus.ACTIVE,
    ).count()

    # Count claims this month
    from datetime import timedelta
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    claims_this_month = db.query(PDCNClaim).filter(
        PDCNClaim.tenant_id == current_user.tenant_id,
        PDCNClaim.created_at >= month_start,
    ).count()

    return {
        "plan": plan_dict(plan) if plan else None,
        "billing_cycle": sub.billing_cycle,
        "current_users": user_count,
        "claims_this_month": claims_this_month,
        "limits": {
            "max_users": plan.max_users if plan else None,
            "max_claims": plan.max_claims_per_month if plan else None,
            "max_storage_gb": plan.max_storage_gb if plan else 5,
        }
    }
