"""
Seed script – creates the super admin account and sample tenant data.
Run: python seed.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from app.database.session import SessionLocal, engine
from app.models import (
    Base, User, Tenant, UserRole, UserStatus, TenantStatus, AuthProvider
)
from app.auth.security import hash_password
from app.config import settings


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # ── Super Admin ──────────────────────────────────────────────
        sa = db.query(User).filter(User.email == settings.SUPER_ADMIN_EMAIL).first()
        if not sa:
            sa = User(
                full_name=settings.SUPER_ADMIN_NAME,
                email=settings.SUPER_ADMIN_EMAIL,
                hashed_password=hash_password(settings.SUPER_ADMIN_PASSWORD),
                role=UserRole.SUPER_ADMIN,
                status=UserStatus.ACTIVE,
                email_verified=True,
            )
            db.add(sa)
            db.commit()
            print(f"✓ Super admin created: {settings.SUPER_ADMIN_EMAIL}")
        else:
            print("  Super admin already exists – skipping.")

        # ── Demo Tenant ──────────────────────────────────────────────
        demo = db.query(Tenant).filter(Tenant.slug == "acme-corp").first()
        if not demo:
            demo = Tenant(
                company_name="Acme Corp",
                slug="acme-corp",
                status=TenantStatus.ACTIVE,
                trial_start=datetime.utcnow() - timedelta(days=5),
                trial_end=datetime.utcnow() + timedelta(days=5),
            )
            db.add(demo)
            db.flush()

            tenant_admin = User(
                tenant_id=demo.id,
                full_name="Acme Admin",
                email="admin@acme.com",
                hashed_password=hash_password("Admin@1234"),
                role=UserRole.TENANT_ADMIN,
                status=UserStatus.ACTIVE,
                email_verified=True,
            )
            db.add(tenant_admin)

            # Sample users
            roles = [UserRole.CN_TEAM, UserRole.FINANCE_TEAM, UserRole.CFA_TEAM, UserRole.DEALER]
            names = ["Alice Chen", "Bob Finance", "Carol CFA", "Dave Dealer"]
            for name, role in zip(names, roles):
                u = User(
                    tenant_id=demo.id,
                    full_name=name,
                    email=f"{name.split()[0].lower()}@acme.com",
                    hashed_password=hash_password("User@1234"),
                    role=role,
                    status=UserStatus.ACTIVE,
                    email_verified=True,
                )
                db.add(u)

            db.commit()
            print("✓ Demo tenant 'Acme Corp' created with 5 users")
        else:
            print("  Demo tenant already exists – skipping.")

        print("\n══════════════════════════════════════════")
        print("  Seed complete!")
        print(f"  Super Admin  → {settings.SUPER_ADMIN_EMAIL} / {settings.SUPER_ADMIN_PASSWORD}")
        print("  Tenant Admin → admin@acme.com / Admin@1234")
        print("══════════════════════════════════════════\n")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
