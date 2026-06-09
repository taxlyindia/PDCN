from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field, field_validator
import re

from app.models import TenantStatus, UserStatus, UserRole, AuthProvider


# ─────────────────────────── Auth Schemas ───────────────────────────

class SignupRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    mobile: Optional[str] = Field(None, max_length=20)
    password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v):
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v


# ─────────────────────────── Tenant Schemas ───────────────────────────

class TenantOut(BaseModel):
    id: uuid.UUID
    company_name: str
    slug: str
    status: TenantStatus
    trial_start: Optional[datetime]
    trial_end: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    user_count: Optional[int] = 0
    trial_days_remaining: Optional[int] = None

    model_config = {"from_attributes": True}


class TenantListResponse(BaseModel):
    tenants: List[TenantOut]
    total: int
    page: int
    per_page: int


class TenantStatusUpdate(BaseModel):
    status: TenantStatus


class TenantExtendTrial(BaseModel):
    days: int = Field(..., ge=1, le=365)


# ─────────────────────────── User Schemas ───────────────────────────

class UserCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    mobile: Optional[str] = Field(None, max_length=20)
    role: UserRole = UserRole.DEALER
    is_finance_team: bool = False
    is_cfa_team: bool = False
    password: str = Field(..., min_length=6)  # Relaxed for admin-created users
    # Distributor-specific optional fields
    dealer_series:    Optional[str] = None
    sap_code:         Optional[str] = None
    business_group:   Optional[str] = None
    region:           Optional[str] = None
    city:             Optional[str] = None
    state:            Optional[str] = None
    credit_check:     Optional[str] = None
    distributor_name: Optional[str] = None

    @field_validator("role", mode="before")
    @classmethod
    def coerce_role(cls, v):
        if isinstance(v, str):
            return v.lower().strip()
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    mobile: Optional[str] = Field(None, max_length=20)
    role: Optional[UserRole] = None
    is_finance_team: Optional[bool] = None
    is_cfa_team: Optional[bool] = None


class UserOut(BaseModel):
    id: uuid.UUID
    tenant_id: Optional[uuid.UUID]
    full_name: str
    email: str
    mobile: Optional[str]
    role: UserRole
    is_finance_team: bool = False
    is_cfa_team: bool = False
    status: UserStatus
    auth_provider: AuthProvider
    email_verified: bool
    last_login: Optional[datetime]
    created_at: datetime
    # Dealer fields
    dealer_series: Optional[str] = None
    sap_code: Optional[str] = None
    business_group: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    credit_check: Optional[str] = None
    distributor_name: Optional[str] = None

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: List[UserOut]
    total: int
    page: int
    per_page: int


class UserStatusUpdate(BaseModel):
    status: UserStatus


class AdminResetPassword(BaseModel):
    new_password: str = Field(..., min_length=8)


# ─────────────────────────── Dashboard Schemas ───────────────────────────

class SuperAdminDashboard(BaseModel):
    total_tenants: int
    active_tenants: int
    trial_tenants: int
    pending_tenants: int
    disabled_tenants: int
    total_users: int
    new_tenants_this_month: int
    recent_logins: int


class TenantDashboard(BaseModel):
    total_users: int
    active_users: int
    disabled_users: int
    recent_activity: int


# ─────────────────────────── Log Schemas ───────────────────────────

class LoginLogOut(BaseModel):
    id: uuid.UUID
    email: str
    ip_address: Optional[str]
    success: bool
    failure_reason: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityLogOut(BaseModel):
    id: uuid.UUID
    action: str
    resource: Optional[str]
    resource_id: Optional[str]
    details: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
    user: Optional[UserOut] = None

    model_config = {"from_attributes": True}


# ─────────────────────────── Generic ───────────────────────────

class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str
