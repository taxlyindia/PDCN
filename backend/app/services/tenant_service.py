from datetime import datetime, timedelta
from typing import Optional, List, Tuple
import uuid

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Tenant, TenantStatus, User, UserRole, UserStatus
from app.auth.security import hash_password
from app.config import settings
from app.utils.helpers import make_unique_slug
from app.utils.email import send_trial_expiry_notification
from app.schemas import SignupRequest


def create_tenant_with_admin(db: Session, data: SignupRequest) -> Tuple[Tenant, User]:
    """Register a new tenant and create its admin user."""
    slug = make_unique_slug(data.company_name, db)
    trial_end = datetime.utcnow() + timedelta(days=settings.TRIAL_DAYS)

    tenant = Tenant(
        company_name=data.company_name,
        slug=slug,
        status=TenantStatus.TRIAL,
        trial_start=datetime.utcnow(),
        trial_end=trial_end,
    )
    db.add(tenant)
    db.flush()  # get tenant.id before creating user

    user = User(
        tenant_id=tenant.id,
        full_name=data.full_name,
        email=data.email,
        mobile=data.mobile,
        hashed_password=hash_password(data.password),
        role=UserRole.TENANT_ADMIN,
        status=UserStatus.ACTIVE,
        email_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(tenant)
    db.refresh(user)
    return tenant, user


def create_tenant_with_google(
    db: Session,
    company_name: str,
    full_name: str,
    email: str,
    google_id: str,
) -> Tuple[Tenant, User]:
    """Register tenant via Google OAuth."""
    from app.models import AuthProvider
    slug = make_unique_slug(company_name, db)
    trial_end = datetime.utcnow() + timedelta(days=settings.TRIAL_DAYS)

    tenant = Tenant(
        company_name=company_name,
        slug=slug,
        status=TenantStatus.TRIAL,
        trial_start=datetime.utcnow(),
        trial_end=trial_end,
    )
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        full_name=full_name,
        email=email,
        google_id=google_id,
        auth_provider=AuthProvider.GOOGLE,
        role=UserRole.TENANT_ADMIN,
        status=UserStatus.ACTIVE,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(tenant)
    db.refresh(user)
    return tenant, user


def check_and_expire_trials(db: Session) -> int:
    """
    Background task: move expired TRIAL tenants to PENDING.
    Returns count of tenants updated.
    """
    now = datetime.utcnow()
    expired = (
        db.query(Tenant)
        .filter(Tenant.status == TenantStatus.TRIAL, Tenant.trial_end <= now)
        .all()
    )
    for tenant in expired:
        tenant.status = TenantStatus.PENDING
        # Notify admin user
        admin = db.query(User).filter(
            User.tenant_id == tenant.id,
            User.role == UserRole.TENANT_ADMIN,
            User.status == UserStatus.ACTIVE,
        ).first()
        # Fire-and-forget (non-blocking in sync context)
        import asyncio
        if admin:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(send_trial_expiry_notification(admin.email, tenant.company_name))
            except Exception:
                pass
    db.commit()
    return len(expired)


def get_tenant_stats(db: Session, tenant_id: uuid.UUID) -> dict:
    users_q = db.query(User).filter(User.tenant_id == tenant_id, User.status != UserStatus.DELETED)
    total = users_q.count()
    active = users_q.filter(User.status == UserStatus.ACTIVE).count()
    disabled = users_q.filter(User.status == UserStatus.DISABLED).count()
    return {"total_users": total, "active_users": active, "disabled_users": disabled}
