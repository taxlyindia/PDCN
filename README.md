# 🚀 Multi-Tenant CRM SaaS Platform

A full-featured, production-ready Multi-Tenant CRM built with **FastAPI**, **PostgreSQL**, and a modern dark-theme frontend.

---

## 📦 Tech Stack

| Layer        | Technology                              |
|-------------|------------------------------------------|
| Backend      | FastAPI (Python 3.10+)                  |
| Database     | PostgreSQL 14+                           |
| ORM          | SQLAlchemy + Alembic                     |
| Auth         | JWT (RS256) + Google OAuth 2.0          |
| Security     | bcrypt, CSRF middleware, tenant isolation|
| Frontend     | HTML5, CSS3 (dark theme), Vanilla JS    |
| Fonts        | Syne + Inter (Google Fonts)             |
| Email        | aiosmtplib (async SMTP)                 |

---

## 🗂️ Project Structure

```
crm/
├── start.bat                    # Windows one-click startup
├── README.md
│
├── backend/
│   ├── main.py                  # FastAPI app entrypoint
│   ├── seed.py                  # Demo data seeder
│   ├── requirements.txt
│   ├── .env.example             # Environment variables template
│   ├── alembic.ini
│   ├── alembic/
│   │   └── env.py
│   └── app/
│       ├── config.py            # Settings (Pydantic)
│       ├── database/
│       │   └── session.py       # DB engine + session
│       ├── models/              # SQLAlchemy models
│       ├── schemas/             # Pydantic schemas
│       ├── auth/
│       │   ├── security.py      # JWT, hashing, tokens
│       │   └── dependencies.py  # FastAPI dependencies
│       ├── services/
│       │   └── tenant_service.py
│       ├── utils/
│       │   ├── email.py
│       │   └── helpers.py
│       ├── middlewares/
│       │   └── security.py
│       └── api/v1/
│           └── endpoints/
│               ├── auth.py      # /api/v1/auth/*
│               ├── admin.py     # /api/v1/admin/*
│               └── tenant.py   # /api/v1/tenant/*
│
└── frontend/
    ├── templates/
    │   ├── login.html
    │   ├── forgot-password.html
    │   ├── reset-password.html
    │   ├── oauth-callback.html
    │   ├── admin-dashboard.html
    │   ├── admin-tenants.html
    │   ├── admin-users.html
    │   ├── admin-logs.html
    │   ├── tenant-dashboard.html
    │   ├── tenant-users.html
    │   ├── tenant-profile.html
    │   └── tenant-logs.html
    └── static/
        ├── css/
        │   └── dashboard.css
        └── js/
            └── app.js
```

---

## ⚡ Quick Start (Windows)

### Prerequisites
- Python 3.10 or higher
- PostgreSQL 14+ running locally
- Git (optional)

### 1. Clone / Download the project

```bash
git clone <repo-url>
cd crm
```

### 2. Set up PostgreSQL database

```sql
-- In psql or pgAdmin:
CREATE DATABASE crm_db;
CREATE USER crm_user WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE crm_db TO crm_user;
```

### 3. Configure environment

```bash
cd backend
copy .env.example .env
```

Edit `.env` with your values:
```env
DATABASE_URL=postgresql://crm_user:yourpassword@localhost:5432/crm_db
SECRET_KEY=your-super-secret-jwt-key-change-this
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your-app-password
SUPER_ADMIN_EMAIL=admin@yourcrm.com
SUPER_ADMIN_PASSWORD=SuperAdmin@123
```

### 4. Run the application

Simply double-click **`start.bat`** or from command line:

```bat
start.bat
```

This will:
1. ✅ Create a Python virtual environment
2. ✅ Install all dependencies
3. ✅ Run database migrations
4. ✅ Seed demo data (first run only)
5. ✅ Start the FastAPI server on `http://localhost:8000`
6. ✅ Open the login page in your browser

---

## 🐧 Manual Setup (Linux / macOS)

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Linux/macOS
pip install -r requirements.txt

cp .env.example .env            # Edit with your values

alembic upgrade head            # Run migrations
python seed.py                  # Seed demo data

uvicorn main:app --reload --port 8000
```

Then open: `http://localhost:8000/templates/login.html`

---

## 🔑 Demo Credentials

| Role           | Email                  | Password       |
|----------------|------------------------|----------------|
| Super Admin    | admin@yourcrm.com      | SuperAdmin@123 |
| Tenant Admin   | admin@acme.com         | Admin@1234     |
| CN Team User   | alice@acme.com         | User@1234      |
| Finance User   | bob@acme.com           | User@1234      |
| CFA User       | carol@acme.com         | User@1234      |
| Dealer         | dave@acme.com          | User@1234      |

---

## 🗺️ Application Routes

### Public
| Path | Description |
|------|-------------|
| `/templates/login.html` | Login & Signup |
| `/templates/forgot-password.html` | Forgot password |
| `/templates/reset-password.html` | Reset password via email link |
| `/templates/oauth-callback.html` | Google OAuth redirect handler |

### Super Admin Panel
| Path | Description |
|------|-------------|
| `/templates/admin-dashboard.html` | Platform overview & analytics |
| `/templates/admin-tenants.html` | Manage all tenants |
| `/templates/admin-users.html` | View all platform users |
| `/templates/admin-logs.html` | Audit & login logs |

### Tenant Panel
| Path | Description |
|------|-------------|
| `/templates/tenant-dashboard.html` | Tenant CRM dashboard |
| `/templates/tenant-users.html` | Manage tenant users |
| `/templates/tenant-profile.html` | Profile & password change |
| `/templates/tenant-logs.html` | Activity & login history |

---

## 🔌 API Reference

Interactive docs: `http://localhost:8000/docs`

### Auth Endpoints (`/api/v1/auth/`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/signup` | Register new tenant |
| POST | `/login` | Login with email + password |
| POST | `/refresh` | Refresh access token |
| POST | `/logout` | Logout (revoke refresh token) |
| POST | `/forgot-password` | Send password reset email |
| POST | `/reset-password` | Reset password via token |
| POST | `/change-password` | Change password (authenticated) |
| GET  | `/google/login` | Initiate Google OAuth |
| GET  | `/google/callback` | Google OAuth callback |
| GET  | `/me` | Get current user info |

### Admin Endpoints (`/api/v1/admin/`) — Super Admin only
| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Platform stats |
| GET | `/tenants` | List all tenants |
| GET | `/tenants/{id}` | Get tenant details |
| PATCH | `/tenants/{id}/approve` | Approve tenant |
| PATCH | `/tenants/{id}/status` | Enable/disable tenant |
| PATCH | `/tenants/{id}/extend-trial` | Extend trial period |
| DELETE | `/tenants/{id}` | Delete tenant |
| GET | `/users` | All platform users |
| GET | `/login-logs` | Platform login logs |
| GET | `/activity-logs` | Platform activity logs |

### Tenant Endpoints (`/api/v1/tenant/`) — Tenant users only
| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard` | Tenant stats |
| GET | `/users` | List tenant users |
| POST | `/users` | Create user |
| GET | `/users/{id}` | Get user |
| PATCH | `/users/{id}` | Update user |
| PATCH | `/users/{id}/status` | Enable/disable user |
| DELETE | `/users/{id}` | Delete user |
| POST | `/users/{id}/reset-password` | Reset user password |
| GET | `/profile` | Get own profile |
| GET | `/activity-logs` | Tenant activity logs |

---

## 🏗️ Architecture

### Multi-Tenancy
- Each tenant has a unique `tenant_id` (UUID)
- All user data is scoped by `tenant_id` foreign key
- `TenantIsolationMiddleware` validates cross-tenant access attempts
- Super Admin has `tenant_id = NULL` and bypasses isolation

### Tenant Lifecycle
```
Signup ──► TRIAL (10 days auto-active)
              │
              ▼ (after 10 days, automated)
           PENDING ──► Admin Approves ──► ACTIVE
              │
              ▼
           DISABLED (admin can disable any time)
              │
              ▼
           DELETED (soft delete)
```

### Authentication Flow
```
Login ──► Verify credentials ──► Issue Access Token (30min) + Refresh Token (7d)
                                        │
                                        ▼
                                  API Request with Bearer token
                                        │
                                        ▼
                                  Token expired? ──► POST /auth/refresh ──► New tokens
```

---

## 🔧 Configuration Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Required |
| `SECRET_KEY` | JWT signing secret | Required |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL | `7` |
| `TRIAL_DAYS` | Trial period duration | `10` |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | Optional |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret | Optional |
| `GOOGLE_REDIRECT_URI` | OAuth callback URL | `http://localhost:8000/api/v1/auth/google/callback` |
| `SMTP_HOST` | Email SMTP host | `smtp.gmail.com` |
| `SMTP_PORT` | Email SMTP port | `587` |
| `SMTP_USER` | Email sender address | Optional |
| `SMTP_PASSWORD` | Email app password | Optional |
| `SUPER_ADMIN_EMAIL` | Super admin email | `admin@yourcrm.com` |
| `SUPER_ADMIN_PASSWORD` | Super admin password | `SuperAdmin@123` |
| `FRONTEND_URL` | Frontend base URL for email links | `http://localhost:8000` |

---

## 🔒 Security Features

- **JWT Authentication** with short-lived access tokens (30 min)
- **Refresh Token Rotation** — each use issues a new refresh token
- **bcrypt** password hashing (cost factor 12)
- **Soft Deletes** — users/tenants are never hard-deleted by default
- **Tenant Isolation Middleware** — prevents cross-tenant data access
- **Security Headers** — `X-Frame-Options`, `X-Content-Type-Options`, `HSTS`
- **Input Validation** — all inputs validated via Pydantic schemas
- **Audit Logging** — all sensitive actions logged with user + IP
- **Failed Login Tracking** — logged per user per IP
- **CORS** — configurable allowed origins

---

## 📧 Email Setup (Gmail)

1. Enable 2FA on your Google account
2. Go to: Google Account → Security → App Passwords
3. Create an app password for "Mail"
4. Use that password as `SMTP_PASSWORD` in `.env`

> **Dev Mode:** If SMTP is not configured, emails are logged to the console instead of being sent.

---

## 🗄️ Database Migrations

```bash
# Create a new migration (after changing models)
alembic revision --autogenerate -m "describe your change"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1

# View migration history
alembic history
```

---

## 🐛 Troubleshooting

**`Could not connect to database`**
- Verify PostgreSQL is running: `pg_ctl status`
- Check `DATABASE_URL` in `.env`

**`Module not found` errors**
- Ensure venv is activated: `venv\Scripts\activate`
- Run: `pip install -r requirements.txt`

**Google OAuth not working**
- Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`
- Add `http://localhost:8000/api/v1/auth/google/callback` to your Google Cloud Console redirect URIs

**Emails not sending**
- In dev mode, check the terminal — emails are printed to console
- For production, verify SMTP credentials and use an App Password for Gmail

---

## 📝 License

MIT License — free for personal and commercial use.
