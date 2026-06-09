"""
Standalone migration script — uses raw psycopg2.
Run: python migrate.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app.config import settings
import psycopg2

def get_dsn():
    return settings.DATABASE_URL.replace("postgresql+psycopg2", "postgresql")

def run():
    dsn = get_dsn()
    print("  [migrate] Connecting to database...")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()

    print("  [migrate] Creating base tables if not exist...")

    # ── Enums (create only if missing — we will migrate to VARCHAR below) ──────
    for sql in [
        "DO $$ BEGIN CREATE TYPE tenantstatus AS ENUM ('trial','active','pending','disabled','deleted'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE userstatus AS ENUM ('active','disabled','deleted'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE userrole AS ENUM ('super_admin','tenant_admin','cn_team','finance_team','cfa_team','dealer'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
        "DO $$ BEGIN CREATE TYPE authprovider AS ENUM ('local','google'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
    ]:
        cur.execute(sql)

    # ── Add finance_cfa_team to userrole if missing ───────────────────────────
    cur.execute("SELECT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='finance_cfa_team' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='userrole'));")
    if not cur.fetchone()[0]:
        print("  [migrate] Adding 'finance_cfa_team' to userrole enum...")
        cur.execute("ALTER TYPE userrole ADD VALUE 'finance_cfa_team';")
    else:
        print("  [migrate] 'finance_cfa_team' already exists.")

    # ── Create tenants table ──────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            company_name VARCHAR(255) NOT NULL,
            slug VARCHAR(100) UNIQUE NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'trial',
            trial_start TIMESTAMP,
            trial_end TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # ── Create users table ────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID REFERENCES tenants(id),
            full_name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            mobile VARCHAR(20),
            hashed_password VARCHAR(255),
            role VARCHAR(50) NOT NULL DEFAULT 'tenant_admin',
            status VARCHAR(50) NOT NULL DEFAULT 'active',
            auth_provider VARCHAR(50) NOT NULL DEFAULT 'local',
            google_id VARCHAR(255) UNIQUE,
            is_finance_team BOOLEAN NOT NULL DEFAULT false,
            is_cfa_team BOOLEAN NOT NULL DEFAULT false,
            email_verified BOOLEAN DEFAULT false,
            last_login TIMESTAMP,
            failed_login_attempts INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            deleted_at TIMESTAMP,
            CONSTRAINT uq_user_email_tenant UNIQUE (email, tenant_id)
        );
    """)

    # ── CRITICAL: Convert any existing enum-typed columns to VARCHAR ──────────
    # Also lowercase all stored values (old enum stored 'TENANT_ADMIN' not 'tenant_admin')
    print("  [migrate] Converting enum columns to VARCHAR and lowercasing values...")
    enum_cols = [
        ("users",   "role"),
        ("users",   "status"),
        ("users",   "auth_provider"),
        ("tenants", "status"),
    ]
    for tbl, col in enum_cols:
        cur.execute("SELECT data_type FROM information_schema.columns WHERE table_name=%s AND column_name=%s", (tbl, col))
        row = cur.fetchone()
        if not row:
            print(f"  [migrate] {tbl}.{col} does not exist yet, skipping.")
            continue
        dtype = row[0].lower()
        if dtype == 'user-defined':
            print(f"  [migrate] {tbl}.{col}: converting from enum to varchar(50) with lowercase...")
            cur.execute(f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE varchar(50) USING lower({col}::text)")
        else:
            # Already varchar — lowercase any UPPERCASE legacy values
            cur.execute(f"UPDATE {tbl} SET {col} = lower({col}) WHERE {col} IS NOT NULL AND {col} != lower({col})")
            affected = cur.statusmessage
            print(f"  [migrate] {tbl}.{col}: already varchar, lowercased values ({affected}).")

    # ── Add is_finance_team / is_cfa_team if missing ──────────────────────────
    for col, default in [("is_finance_team", "false"), ("is_cfa_team", "false")]:
        cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name=%s);", (col,))
        if not cur.fetchone()[0]:
            print(f"  [migrate] Adding column users.{col}...")
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} BOOLEAN NOT NULL DEFAULT {default};")
        else:
            print(f"  [migrate] users.{col} already exists.")

    # ── Back-fill boolean flags ───────────────────────────────────────────────
    print("  [migrate] Back-filling is_finance_team / is_cfa_team flags...")
    cur.execute("""
        UPDATE users SET
            is_finance_team = (role IN ('finance_team', 'finance_cfa_team')),
            is_cfa_team     = (role IN ('cfa_team',     'finance_cfa_team'))
        WHERE is_finance_team = false AND is_cfa_team = false
          AND role IN ('finance_team', 'cfa_team', 'finance_cfa_team');
    """)

    # ── Remaining tables ──────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            token VARCHAR(512) UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            revoked BOOLEAN DEFAULT false,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            token VARCHAR(512) UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used BOOLEAN DEFAULT false,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            tenant_id UUID REFERENCES tenants(id),
            email VARCHAR(255) NOT NULL,
            ip_address VARCHAR(50),
            user_agent TEXT,
            success BOOLEAN NOT NULL,
            failure_reason VARCHAR(255),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id),
            tenant_id UUID REFERENCES tenants(id),
            action VARCHAR(255) NOT NULL,
            resource VARCHAR(100),
            resource_id VARCHAR(255),
            details TEXT,
            ip_address VARCHAR(50),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # ── Stamp alembic version ─────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL,
            CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
        );
    """)
    cur.execute("SELECT version_num FROM alembic_version;")
    rows = cur.fetchall()
    if not rows:
        cur.execute("INSERT INTO alembic_version (version_num) VALUES ('002_varchar_enums');")
        print("  [migrate] Alembic version stamped.")
    else:
        cur.execute("DELETE FROM alembic_version;")
        cur.execute("INSERT INTO alembic_version (version_num) VALUES ('002_varchar_enums');")
        print("  [migrate] Alembic version updated.")

    cur.close()
    conn.close()
    print("  [migrate] All migrations complete.")

if __name__ == "__main__":
    run()


def run_pdcn():
    """Add PDCN tables — called from run() automatically."""
    import psycopg2
    from app.config import settings
    dsn = settings.DATABASE_URL.replace("postgresql+psycopg2", "postgresql")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()

    print("  [migrate] Creating PDCN tables...")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sales_register (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            upload_batch VARCHAR(100) NOT NULL,
            invoice_no VARCHAR(100) NOT NULL,
            invoice_date TIMESTAMP NOT NULL,
            dealer_id UUID REFERENCES users(id),
            dealer_name VARCHAR(255) NOT NULL,
            dealer_code VARCHAR(100),
            product_name VARCHAR(255) NOT NULL,
            product_code VARCHAR(100),
            batch_no VARCHAR(100),
            quantity INTEGER NOT NULL,
            rate VARCHAR(50) NOT NULL,
            tax VARCHAR(50),
            net_amount VARCHAR(50),
            uploaded_by UUID REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_sales_register_entry UNIQUE (tenant_id, invoice_no, product_code, batch_no)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS qty_utilization_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            invoice_no VARCHAR(100) NOT NULL,
            product_code VARCHAR(100) NOT NULL,
            batch_no VARCHAR(100),
            total_sold_qty INTEGER NOT NULL,
            claimed_qty INTEGER NOT NULL DEFAULT 0,
            balance_qty INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_qty_ledger UNIQUE (tenant_id, invoice_no, product_code, batch_no)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pdcn_claims (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            claim_no VARCHAR(50) NOT NULL UNIQUE,
            dealer_id UUID NOT NULL REFERENCES users(id),
            dealer_name VARCHAR(255) NOT NULL,
            dealer_code VARCHAR(100),
            request_date TIMESTAMP DEFAULT NOW(),
            region VARCHAR(100),
            state VARCHAR(100),
            sales_person VARCHAR(255),
            claim_type VARCHAR(50) DEFAULT 'pdcn',
            status VARCHAR(50) NOT NULL DEFAULT 'draft',
            total_qty INTEGER DEFAULT 0,
            total_amount VARCHAR(50) DEFAULT '0',
            cn_remarks TEXT,
            finance_remarks TEXT,
            cfa_remarks TEXT,
            cn_actioned_by UUID REFERENCES users(id),
            cn_actioned_at TIMESTAMP,
            fin_actioned_by UUID REFERENCES users(id),
            fin_actioned_at TIMESTAMP,
            cfa_actioned_by UUID REFERENCES users(id),
            cfa_actioned_at TIMESTAMP,
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            submitted_at TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pdcn_line_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id UUID NOT NULL REFERENCES pdcn_claims(id) ON DELETE CASCADE,
            invoice_no VARCHAR(100) NOT NULL,
            invoice_date TIMESTAMP,
            product_name VARCHAR(255) NOT NULL,
            product_code VARCHAR(100),
            batch_no VARCHAR(100),
            quantity INTEGER NOT NULL,
            invoice_rate VARCHAR(50) NOT NULL,
            claim_rate VARCHAR(50) NOT NULL,
            difference_amt VARCHAR(50),
            tax VARCHAR(50),
            total_claim_amt VARCHAR(50),
            reason TEXT,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pdcn_attachments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id UUID NOT NULL REFERENCES pdcn_claims(id) ON DELETE CASCADE,
            filename VARCHAR(255) NOT NULL,
            original_name VARCHAR(255) NOT NULL,
            file_size INTEGER,
            mime_type VARCHAR(100),
            uploaded_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pdcn_approval_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id UUID NOT NULL REFERENCES pdcn_claims(id) ON DELETE CASCADE,
            action VARCHAR(100) NOT NULL,
            from_status VARCHAR(50),
            to_status VARCHAR(50) NOT NULL,
            actioned_by UUID NOT NULL REFERENCES users(id),
            actioned_by_name VARCHAR(255),
            actioned_by_role VARCHAR(50),
            remarks TEXT,
            ip_address VARCHAR(50),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS credit_notes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id UUID NOT NULL UNIQUE REFERENCES pdcn_claims(id),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            cn_number VARCHAR(100) NOT NULL,
            cn_date TIMESTAMP NOT NULL,
            cn_amount VARCHAR(50) NOT NULL,
            cn_filename VARCHAR(255),
            cn_original_name VARCHAR(255),
            remarks TEXT,
            created_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pdcn_notifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            user_id UUID NOT NULL REFERENCES users(id),
            claim_id UUID REFERENCES pdcn_claims(id),
            title VARCHAR(255) NOT NULL,
            message TEXT NOT NULL,
            is_read BOOLEAN DEFAULT false,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # uploads directory
    import os
    os.makedirs("uploads/pdcn", exist_ok=True)

    cur.close()
    conn.close()
    print("  [migrate] PDCN tables created.")



def run_chat():
    """Create chat tables."""
    import psycopg2
    from app.config import settings
    dsn = settings.DATABASE_URL.replace("postgresql+psycopg2", "postgresql")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    print("  [migrate] Creating chat tables...")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            conversation_key VARCHAR(200) NOT NULL,
            participant_a UUID NOT NULL REFERENCES users(id),
            participant_b UUID NOT NULL REFERENCES users(id),
            last_message TEXT,
            last_message_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            CONSTRAINT uq_chat_conversation UNIQUE (tenant_id, conversation_key)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
            sender_id UUID NOT NULL REFERENCES users(id),
            sender_name VARCHAR(255),
            sender_role VARCHAR(50),
            message TEXT NOT NULL,
            is_read BOOLEAN DEFAULT false,
            claim_ref UUID,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.close()
    conn.close()
    print("  [migrate] Chat tables created.")


def run_pricing():
    """Create pricing plan tables and seed defaults."""
    import psycopg2, json
    from app.config import settings
    dsn = settings.DATABASE_URL.replace("postgresql+psycopg2", "postgresql")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    print("  [migrate] Creating pricing & video tables...")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pricing_plans (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL,
            slug VARCHAR(50) UNIQUE NOT NULL,
            description TEXT,
            monthly_price INTEGER NOT NULL DEFAULT 0,
            annual_price INTEGER NOT NULL DEFAULT 0,
            annual_discount_pct INTEGER NOT NULL DEFAULT 0,
            max_users INTEGER,
            max_claims_per_month INTEGER,
            max_storage_gb INTEGER NOT NULL DEFAULT 5,
            features TEXT,
            is_active BOOLEAN DEFAULT true,
            is_featured BOOLEAN DEFAULT false,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            updated_by UUID REFERENCES users(id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenant_subscriptions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID UNIQUE NOT NULL REFERENCES tenants(id),
            plan_id UUID NOT NULL REFERENCES pricing_plans(id),
            billing_cycle VARCHAR(20) DEFAULT 'monthly',
            started_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP,
            claims_used INTEGER DEFAULT 0,
            claims_reset_at TIMESTAMP,
            is_active BOOLEAN DEFAULT true,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pdcn_videos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            claim_id UUID NOT NULL REFERENCES pdcn_claims(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            filename VARCHAR(255) NOT NULL,
            original_name VARCHAR(255) NOT NULL,
            file_size INTEGER,
            duration_secs INTEGER,
            mime_type VARCHAR(100),
            thumbnail VARCHAR(255),
            description TEXT,
            uploaded_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Seed default pricing plans if not exist
    cur.execute("SELECT COUNT(*) FROM pricing_plans;")
    if cur.fetchone()[0] == 0:
        plans = [
            {
                "name": "Starter",
                "slug": "starter",
                "description": "Full 5-stage PDCN workflow for small teams",
                "monthly_price": 4999,
                "annual_price": 47990,
                "annual_discount_pct": 20,
                "max_users": 5,
                "max_claims_per_month": 100,
                "max_storage_gb": 5,
                "is_featured": False,
                "sort_order": 1,
                "features": json.dumps([
                    "Full 5-stage workflow",
                    "Up to 5 team users",
                    "100 CN / month",
                    "Sales register upload",
                    "Excel exports",
                    "Internal chat",
                    "Email notifications",
                    "5 GB storage"
                ])
            },
            {
                "name": "Professional",
                "slug": "professional",
                "description": "Unlimited claims for growing distribution businesses",
                "monthly_price": 12999,
                "annual_price": 124790,
                "annual_discount_pct": 20,
                "max_users": 20,
                "max_claims_per_month": None,
                "max_storage_gb": 50,
                "is_featured": True,
                "sort_order": 2,
                "features": json.dumps([
                    "Everything in Starter",
                    "Up to 20 team users",
                    "Unlimited CN / month",
                    "Video attachments on claims",
                    "Priority support",
                    "Advanced reports",
                    "Qty utilization ledger",
                    "50 GB storage"
                ])
            },
            {
                "name": "Enterprise",
                "slug": "enterprise",
                "description": "Custom workflows for large-scale operations",
                "monthly_price": 0,
                "annual_price": 0,
                "annual_discount_pct": 0,
                "max_users": None,
                "max_claims_per_month": None,
                "max_storage_gb": 500,
                "is_featured": False,
                "sort_order": 3,
                "features": json.dumps([
                    "Everything in Professional",
                    "Unlimited users",
                    "ERP / SAP integration",
                    "White-label option",
                    "On-premise deployment",
                    "Custom role configuration",
                    "SLA-backed support",
                    "500 GB storage"
                ])
            }
        ]
        for p in plans:
            cur.execute("""
                INSERT INTO pricing_plans
                (name, slug, description, monthly_price, annual_price,
                 annual_discount_pct, max_users, max_claims_per_month,
                 max_storage_gb, features, is_featured, sort_order)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (slug) DO NOTHING
            """, (p["name"], p["slug"], p["description"], p["monthly_price"],
                  p["annual_price"], p["annual_discount_pct"], p["max_users"],
                  p["max_claims_per_month"], p["max_storage_gb"],
                  p["features"], p["is_featured"], p["sort_order"]))
        print("  [migrate] Default pricing plans seeded.")
    else:
        print("  [migrate] Pricing plans already exist.")

    # uploads/videos dir
    import os
    os.makedirs("uploads/videos", exist_ok=True)

    cur.close()
    conn.close()
    print("  [migrate] Pricing & video tables done.")



def run_platform_videos():
    import psycopg2
    from app.config import settings
    dsn = settings.DATABASE_URL.replace("postgresql+psycopg2","postgresql")
    conn = psycopg2.connect(dsn); conn.autocommit=True; cur=conn.cursor()
    print("  [migrate] Creating platform_videos table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS platform_videos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title VARCHAR(255) NOT NULL,
            description TEXT,
            category VARCHAR(100) NOT NULL DEFAULT 'general',
            filename VARCHAR(255) NOT NULL,
            original_name VARCHAR(255) NOT NULL,
            file_size INTEGER,
            mime_type VARCHAR(100),
            thumbnail_url VARCHAR(255),
            duration_secs INTEGER,
            is_published BOOLEAN DEFAULT false,
            view_count INTEGER DEFAULT 0,
            target_roles VARCHAR(255) DEFAULT 'all',
            sort_order INTEGER DEFAULT 0,
            uploaded_by UUID REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """)
    import os; os.makedirs("uploads/platform", exist_ok=True)
    cur.close(); conn.close()
    print("  [migrate] platform_videos table done.")




def run_knowledge_videos():
    """Create knowledge_videos table."""
    import psycopg2, os
    from app.config import settings
    dsn = settings.DATABASE_URL.replace("postgresql+psycopg2", "postgresql")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    print("  [migrate] Creating knowledge_videos table...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_videos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title VARCHAR(255) NOT NULL,
            description TEXT,
            category VARCHAR(100) NOT NULL DEFAULT 'general',
            filename VARCHAR(255) NOT NULL,
            original_name VARCHAR(255) NOT NULL,
            file_size INTEGER,
            duration_secs INTEGER,
            mime_type VARCHAR(100),
            thumbnail VARCHAR(255),
            is_published BOOLEAN DEFAULT false,
            sort_order INTEGER DEFAULT 0,
            view_count INTEGER DEFAULT 0,
            uploaded_by UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """)
    os.makedirs("uploads/knowledge", exist_ok=True)
    cur.close()
    conn.close()
    print("  [migrate] knowledge_videos table done.")


# Patch the existing run() to also call run_pdcn, run_chat, run_pricing
def run_dealer_fields():
    """Add dealer-specific columns to users table using raw psycopg2."""
    dsn = get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    print("  [migrate] Adding dealer fields to users table...")
    dealer_cols = [
        ("dealer_series",    "VARCHAR(20)"),
        ("sap_code",         "VARCHAR(50)"),
        ("business_group",   "VARCHAR(100)"),
        ("region",           "VARCHAR(100)"),
        ("city",             "VARCHAR(100)"),
        ("state",            "VARCHAR(100)"),
        ("credit_check",     "VARCHAR(20)"),
        ("distributor_name", "VARCHAR(255)"),
    ]
    for col, dtype in dealer_cols:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
            conn.commit()
            print(f"  [migrate] users.{col} added.")
        except Exception:
            conn.rollback()
            print(f"  [migrate] users.{col} already exists.")
    cur.close()
    conn.close()

def run_new_lineitem_cols():
    """Add new columns to pdcn_line_items table using raw psycopg2."""
    dsn = get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    print("  [migrate] Adding new columns to pdcn_line_items...")
    item_cols = [
        ("sap_material_code", "VARCHAR(100)"),
        ("brand_code",        "VARCHAR(50)"),
        ("is_manual_invoice", "BOOLEAN DEFAULT FALSE"),
        ("purchase_price",    "VARCHAR(50)"),
        ("billed_to",         "VARCHAR(255)"),
        ("billed_date",       "TIMESTAMP"),
        ("dealer_invoice_no", "VARCHAR(100)"),
        ("credit_note_type",  "VARCHAR(20)"),
    ]
    for col, dtype in item_cols:
        try:
            cur.execute(f"ALTER TABLE pdcn_line_items ADD COLUMN {col} {dtype}")
            conn.commit()
            print(f"  [migrate] pdcn_line_items.{col} added.")
        except Exception:
            conn.rollback()
            print(f"  [migrate] pdcn_line_items.{col} already exists.")
    cur.close()
    conn.close()




def run_sales_register_batch():
    """Create sales_register_batches table."""
    dsn = get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales_register_batches (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id   UUID NOT NULL REFERENCES tenants(id),
                batch_key   VARCHAR(20) NOT NULL,
                month_label VARCHAR(50),
                uploaded_by UUID REFERENCES users(id),
                uploaded_at TIMESTAMP DEFAULT NOW(),
                row_count   INTEGER DEFAULT 0,
                CONSTRAINT uq_sr_batch_tenant_month UNIQUE(tenant_id, batch_key)
            )
        """)
        print("  [migrate] sales_register_batches table created.")
    except Exception as e:
        print(f"  [migrate] sales_register_batches: {e}")
    finally:
        cur.close()
        conn.close()

_original_run = run
def run():
    _original_run()
    run_pdcn()
    run_chat()
    run_pricing()
    run_platform_videos()
    run_knowledge_videos()
    run_dealer_fields()       # dealer columns on users table
    run_new_lineitem_cols()   # new columns on pdcn_line_items
    run_sales_register_batch()  # sales register batch tracking

if __name__ == "__main__":
    run()




