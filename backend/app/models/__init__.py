import enum
import uuid
from datetime import datetime, timedelta

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey,
    Integer, String, Text, UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.session import Base
from app.config import settings


# ─────────────────────────── Enums ───────────────────────────

class TenantStatus(str, enum.Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    PENDING = "pending"         # trial expired, awaiting admin approval
    DISABLED = "disabled"
    DELETED = "deleted"


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    TENANT_ADMIN = "tenant_admin"
    CN_TEAM = "cn_team"
    FINANCE_TEAM = "finance_team"
    CFA_TEAM = "cfa_team"
    FINANCE_CFA_TEAM = "finance_cfa_team"   # holds both Finance + CFA roles
    DEALER = "dealer"


class AuthProvider(str, enum.Enum):
    LOCAL = "local"
    GOOGLE = "google"


# ─────────────────────────── Tenant ───────────────────────────

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(50), default="trial", nullable=False)

    trial_start = Column(DateTime, default=datetime.utcnow)
    trial_end = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    login_logs = relationship("LoginLog", back_populates="tenant")
    activity_logs = relationship("ActivityLog", back_populates="tenant")

    def __repr__(self):
        return f"<Tenant {self.company_name}>"


# ─────────────────────────── User ───────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)  # NULL for super admin

    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, index=True)
    mobile = Column(String(20), nullable=True)
    hashed_password = Column(String(255), nullable=True)  # NULL for OAuth-only users

    role = Column(String(50), nullable=False, default="tenant_admin")
    status = Column(String(50), default="active", nullable=False)
    auth_provider = Column(String(50), default="local", nullable=False)
    google_id = Column(String(255), nullable=True, unique=True)

    # Dealer-specific fields (only populated when role=dealer)
    dealer_series   = Column(String(20), nullable=True)  # e.g. MAX, ABR, etc. for claim numbering
    sap_code        = Column(String(50), nullable=True)
    business_group  = Column(String(100), nullable=True)   # e.g. S.E.T, Recon
    region          = Column(String(100), nullable=True)   # e.g. North, South
    city            = Column(String(100), nullable=True)
    state           = Column(String(100), nullable=True)
    credit_check    = Column(String(20), nullable=True)    # Red / Green
    distributor_name= Column(String(255), nullable=True)   # Official distributor name

    # Dual-role flags (Finance + CFA can be the same person)
    is_finance_team = Column(Boolean, default=False, nullable=False)
    is_cfa_team = Column(Boolean, default=False, nullable=False)

    email_verified = Column(Boolean, default=False)
    last_login = Column(DateTime, nullable=True)
    failed_login_attempts = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # soft delete

    # Relationships
    tenant = relationship("Tenant", back_populates="users")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    password_resets = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    login_logs = relationship("LoginLog", back_populates="user")
    activity_logs = relationship("ActivityLog", back_populates="user")

    __table_args__ = (
        UniqueConstraint("email", "tenant_id", name="uq_user_email_tenant"),
    )

    def __repr__(self):
        return f"<User {self.email}>"


# ─────────────────────────── Tokens ───────────────────────────

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token = Column(String(512), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="refresh_tokens")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token = Column(String(512), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="password_resets")


# ─────────────────────────── Logs ───────────────────────────

class LoginLog(Base):
    __tablename__ = "login_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    email = Column(String(255), nullable=False)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False)
    failure_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="login_logs")
    tenant = relationship("Tenant", back_populates="login_logs")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=True)
    action = Column(String(255), nullable=False)
    resource = Column(String(100), nullable=True)
    resource_id = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="activity_logs")
    tenant = relationship("Tenant", back_populates="activity_logs")


# ═══════════════════════════════════════════════════════════════
#  PDCN CRM MODELS
# ═══════════════════════════════════════════════════════════════

class PDCNStatus(str, enum.Enum):
    DRAFT              = "draft"
    SUBMITTED          = "submitted"
    CN_APPROVED        = "cn_approved"
    CN_REJECTED        = "cn_rejected"
    FINANCE_APPROVED   = "finance_approved"
    FINANCE_REJECTED   = "finance_rejected"
    SENT_BACK          = "sent_back"
    CN_PENDING         = "cn_pending"
    CN_GENERATED       = "cn_generated"
    COMPLETED          = "completed"
    CANCELLED          = "cancelled"


class ClaimType(str, enum.Enum):
    PDCN               = "pdcn"
    SPECIAL_DISCOUNT   = "special_discount"
    PRICE_DIFFERENTIAL = "price_differential"


# ─── Sales Register (master data uploaded by Finance) ─────────
class SalesRegister(Base):
    __tablename__ = "sales_register"
    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id      = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    upload_batch   = Column(String(100), nullable=False)   # e.g. "2024-01"
    invoice_no     = Column(String(100), nullable=False)
    invoice_date   = Column(DateTime, nullable=False)
    dealer_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    dealer_name    = Column(String(255), nullable=False)
    dealer_code    = Column(String(100), nullable=True)
    product_name   = Column(String(255), nullable=False)
    product_code   = Column(String(100), nullable=True)
    batch_no       = Column(String(100), nullable=True)
    quantity       = Column(Integer, nullable=False)
    rate           = Column(String(50), nullable=False)
    tax            = Column(String(50), nullable=True)
    net_amount     = Column(String(50), nullable=True)
    uploaded_by    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_no", "product_code", "batch_no", name="uq_sales_register_entry"),
    )


# ─── Qty Utilization Ledger ────────────────────────────────────
class QtyUtilizationLedger(Base):
    __tablename__ = "qty_utilization_ledger"
    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id      = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    invoice_no     = Column(String(100), nullable=False)
    product_code   = Column(String(100), nullable=False)
    batch_no       = Column(String(100), nullable=True)
    total_sold_qty = Column(Integer, nullable=False)
    claimed_qty    = Column(Integer, nullable=False, default=0)
    balance_qty    = Column(Integer, nullable=False)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_no", "product_code", "batch_no", name="uq_qty_ledger"),
    )


# ─── PDCN Claim Header ─────────────────────────────────────────
class PDCNClaim(Base):
    __tablename__ = "pdcn_claims"
    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id      = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    claim_no       = Column(String(50), nullable=False, unique=True)   # auto-generated
    dealer_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    dealer_name    = Column(String(255), nullable=False)
    dealer_code    = Column(String(100), nullable=True)
    request_date   = Column(DateTime, default=datetime.utcnow)
    region         = Column(String(100), nullable=True)
    state          = Column(String(100), nullable=True)
    sales_person   = Column(String(255), nullable=True)
    claim_type     = Column(String(50), default="pdcn")
    status         = Column(String(50), default="draft", nullable=False)
    total_qty      = Column(Integer, default=0)
    total_amount   = Column(String(50), default="0")
    cn_remarks     = Column(Text, nullable=True)
    finance_remarks= Column(Text, nullable=True)
    cfa_remarks    = Column(Text, nullable=True)
    cn_actioned_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    cn_actioned_at = Column(DateTime, nullable=True)
    fin_actioned_by= Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    fin_actioned_at= Column(DateTime, nullable=True)
    cfa_actioned_by= Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    cfa_actioned_at= Column(DateTime, nullable=True)
    created_by     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_at   = Column(DateTime, nullable=True)

    line_items     = relationship("PDCNLineItem",    back_populates="claim", cascade="all, delete-orphan")
    attachments    = relationship("PDCNAttachment",  back_populates="claim", cascade="all, delete-orphan")
    approval_logs  = relationship("PDCNApprovalLog", back_populates="claim", cascade="all, delete-orphan")
    credit_note    = relationship("CreditNote",      back_populates="claim", uselist=False)


# ─── PDCN Line Items ───────────────────────────────────────────
class PDCNLineItem(Base):
    __tablename__ = "pdcn_line_items"
    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id       = Column(UUID(as_uuid=True), ForeignKey("pdcn_claims.id"), nullable=False)
    sap_material_code = Column(String(100), nullable=True)   # from image: SAP Material Code
    brand_code        = Column(String(50), nullable=True)    # Brand Code
    invoice_no        = Column(String(100), nullable=False)  # ZB Invoice Number
    is_manual_invoice = Column(Boolean, default=False)       # If Manual Invoice?
    invoice_date      = Column(DateTime, nullable=True)      # ZB Invoice Date
    product_name      = Column(String(255), nullable=False)
    product_code      = Column(String(100), nullable=True)
    batch_no          = Column(String(100), nullable=True)
    quantity          = Column(Integer, nullable=False)
    purchase_price    = Column(String(50), nullable=True)    # Purchase Price
    invoice_rate      = Column(String(50), nullable=False)   # Allowed SD Price
    claim_rate        = Column(String(50), nullable=False)   # Selling Price (dealer invoice)
    difference_amt    = Column(String(50), nullable=True)    # Diff Price
    billed_to         = Column(String(255), nullable=True)   # Billed To (hospital/customer)
    billed_date       = Column(DateTime, nullable=True)      # Billed Date
    dealer_invoice_no = Column(String(100), nullable=True)   # Dealer Invoice Number
    credit_note_type  = Column(String(20), nullable=True)    # CR1, CR2, CR3 etc
    tax               = Column(String(50), nullable=True)
    total_claim_amt   = Column(String(50), nullable=True)
    reason            = Column(Text, nullable=True)
    remarks           = Column(Text, nullable=True)
    created_at        = Column(DateTime, default=datetime.utcnow)

    claim          = relationship("PDCNClaim", back_populates="line_items")


# ─── PDCN Attachments ──────────────────────────────────────────
class PDCNAttachment(Base):
    __tablename__ = "pdcn_attachments"
    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id       = Column(UUID(as_uuid=True), ForeignKey("pdcn_claims.id"), nullable=False)
    filename       = Column(String(255), nullable=False)
    original_name  = Column(String(255), nullable=False)
    file_size      = Column(Integer, nullable=True)
    mime_type      = Column(String(100), nullable=True)
    uploaded_by    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at     = Column(DateTime, default=datetime.utcnow)

    claim          = relationship("PDCNClaim", back_populates="attachments")


# ─── Approval Log ──────────────────────────────────────────────
class PDCNApprovalLog(Base):
    __tablename__ = "pdcn_approval_logs"
    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id       = Column(UUID(as_uuid=True), ForeignKey("pdcn_claims.id"), nullable=False)
    action         = Column(String(100), nullable=False)   # SUBMITTED, CN_APPROVED, etc.
    from_status    = Column(String(50), nullable=True)
    to_status      = Column(String(50), nullable=False)
    actioned_by    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    actioned_by_name = Column(String(255), nullable=True)
    actioned_by_role = Column(String(50), nullable=True)
    remarks        = Column(Text, nullable=True)
    ip_address     = Column(String(50), nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow)

    claim          = relationship("PDCNClaim", back_populates="approval_logs")


# ─── Credit Note ───────────────────────────────────────────────
class CreditNote(Base):
    __tablename__ = "credit_notes"
    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id       = Column(UUID(as_uuid=True), ForeignKey("pdcn_claims.id"), nullable=False, unique=True)
    tenant_id      = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    cn_number      = Column(String(100), nullable=False)
    cn_date        = Column(DateTime, nullable=False)
    cn_amount      = Column(String(50), nullable=False)
    cn_filename    = Column(String(255), nullable=True)
    cn_original_name = Column(String(255), nullable=True)
    remarks        = Column(Text, nullable=True)
    created_by     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at     = Column(DateTime, default=datetime.utcnow)

    claim          = relationship("PDCNClaim", back_populates="credit_note")


# ─── In-App Notifications ──────────────────────────────────────
class PDCNNotification(Base):
    __tablename__ = "pdcn_notifications"
    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id      = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id        = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    claim_id       = Column(UUID(as_uuid=True), ForeignKey("pdcn_claims.id"), nullable=True)
    title          = Column(String(255), nullable=False)
    message        = Column(Text, nullable=False)
    is_read        = Column(Boolean, default=False)
    created_at     = Column(DateTime, default=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════
#  INTERNAL CHAT MODELS
# ═══════════════════════════════════════════════════════════════

class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id    = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    # For 1:1 chats — store sorted user IDs as a key so we never duplicate
    conversation_key = Column(String(200), nullable=False)   # "uuid1:uuid2" sorted
    participant_a    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    participant_b    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    last_message     = Column(Text, nullable=True)
    last_message_at  = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    messages         = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_key", name="uq_chat_conversation"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("chat_conversations.id"), nullable=False)
    sender_id       = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    sender_name     = Column(String(255), nullable=True)
    sender_role     = Column(String(50), nullable=True)
    message         = Column(Text, nullable=False)
    is_read         = Column(Boolean, default=False)
    claim_ref       = Column(UUID(as_uuid=True), nullable=True)   # optional PDCN claim reference
    created_at      = Column(DateTime, default=datetime.utcnow)

    conversation    = relationship("ChatConversation", back_populates="messages")


# ═══════════════════════════════════════════════════════════════
#  PRICING & PLAN MODELS
# ═══════════════════════════════════════════════════════════════

class SalesRegisterBatch(Base):
    """Tracks which months have had their sales register uploaded by Finance."""
    __tablename__ = "sales_register_batches"
    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id   = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    batch_key   = Column(String(20), nullable=False)   # "YYYY-MM"  e.g. "2026-05"
    month_label = Column(String(50), nullable=True)    # "May 2026"
    uploaded_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    row_count   = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("tenant_id", "batch_key", name="uq_sr_batch_tenant_month"),
    )


class PricingPlan(Base):
    __tablename__ = "pricing_plans"
    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name                = Column(String(100), nullable=False)          # Starter, Professional, Enterprise
    slug                = Column(String(50), unique=True, nullable=False)  # starter, professional, enterprise
    description         = Column(Text, nullable=True)
    monthly_price       = Column(Integer, nullable=False, default=0)   # in INR (ex-GST)
    annual_price        = Column(Integer, nullable=False, default=0)   # full year ex-GST
    annual_discount_pct = Column(Integer, nullable=False, default=0)   # e.g. 20 for 20%
    max_users           = Column(Integer, nullable=True)               # None = unlimited
    max_claims_per_month= Column(Integer, nullable=True)               # None = unlimited
    max_storage_gb      = Column(Integer, nullable=False, default=5)
    features            = Column(Text, nullable=True)                  # JSON array of feature strings
    is_active           = Column(Boolean, default=True)
    is_featured         = Column(Boolean, default=False)
    sort_order          = Column(Integer, default=0)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by          = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class TenantSubscription(Base):
    __tablename__ = "tenant_subscriptions"
    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id       = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), unique=True, nullable=False)
    plan_id         = Column(UUID(as_uuid=True), ForeignKey("pricing_plans.id"), nullable=False)
    billing_cycle   = Column(String(20), default="monthly")  # monthly | annual
    started_at      = Column(DateTime, default=datetime.utcnow)
    expires_at      = Column(DateTime, nullable=True)
    claims_used     = Column(Integer, default=0)
    claims_reset_at = Column(DateTime, nullable=True)
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── PDCN Video Attachments ────────────────────────────────────
class PDCNVideo(Base):
    __tablename__ = "pdcn_videos"
    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id        = Column(UUID(as_uuid=True), ForeignKey("pdcn_claims.id"), nullable=False)
    tenant_id       = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    filename        = Column(String(255), nullable=False)
    original_name   = Column(String(255), nullable=False)
    file_size       = Column(Integer, nullable=True)
    duration_secs   = Column(Integer, nullable=True)
    mime_type       = Column(String(100), nullable=True)
    thumbnail       = Column(String(255), nullable=True)
    description     = Column(Text, nullable=True)
    uploaded_by     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow)


# ─── Platform Knowledge Videos (uploaded by Super Admin) ──────
class PlatformVideo(Base):
    __tablename__ = "platform_videos"
    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title         = Column(String(255), nullable=False)
    description   = Column(Text, nullable=True)
    category      = Column(String(100), nullable=False, default="general")
    filename      = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_size     = Column(Integer, nullable=True)
    mime_type     = Column(String(100), nullable=True)
    thumbnail_url = Column(String(255), nullable=True)
    duration_secs = Column(Integer, nullable=True)
    is_published  = Column(Boolean, default=False)
    view_count    = Column(Integer, default=0)
    target_roles  = Column(String(255), nullable=True)  # comma-sep roles or "all"
    sort_order    = Column(Integer, default=0)
    uploaded_by   = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── Knowledge / Tutorial Videos (Super Admin uploads) ────────
class KnowledgeVideo(Base):
    __tablename__ = "knowledge_videos"
    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title         = Column(String(255), nullable=False)
    description   = Column(Text, nullable=True)
    category      = Column(String(100), nullable=False, default="general")
    # categories: overview | workflow | dealer | cn_team | finance | cfa | admin
    filename      = Column(String(255), nullable=False)
    original_name = Column(String(255), nullable=False)
    file_size     = Column(Integer, nullable=True)
    duration_secs = Column(Integer, nullable=True)
    mime_type     = Column(String(100), nullable=True)
    thumbnail     = Column(String(255), nullable=True)
    is_published  = Column(Boolean, default=False)
    sort_order    = Column(Integer, default=0)
    view_count    = Column(Integer, default=0)
    uploaded_by   = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
