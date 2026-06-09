from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.security import decode_token
from app.models import User, UserRole, UserStatus, TenantStatus

bearer_scheme = HTTPBearer()


def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = db.query(User).filter(User.id == user_id, User.status != UserStatus.DELETED).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if user.status == UserStatus.DISABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    return user


def get_current_user(user: User = Depends(_get_current_user)) -> User:
    return user


def get_super_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin access required")
    return user


def get_tenant_admin(user: User = Depends(get_current_user)) -> User:
    if user.role not in (UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant Admin access required")
    # Check tenant is active or in trial
    if user.tenant and user.tenant.status in (TenantStatus.DISABLED, TenantStatus.PENDING, TenantStatus.DELETED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not active. Please contact support."
        )
    return user


def get_active_tenant_user(user: User = Depends(get_current_user)) -> User:
    """Any user of an active tenant."""
    if user.role == UserRole.SUPER_ADMIN:
        return user
    if user.tenant and user.tenant.status in (TenantStatus.DISABLED, TenantStatus.PENDING, TenantStatus.DELETED):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your organisation's account is not active."
        )
    return user
