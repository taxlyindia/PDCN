"""
Multi-Tenant CRM – FastAPI Application Entry Point
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.database.session import engine
from app.models import Base  # noqa: F401 – imports all models so metadata is populated
from app.api.v1 import api_router
from app.middlewares.security import TenantIsolationMiddleware, SecurityHeadersMiddleware


# ─────────────────────────── Lifespan ───────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tables are managed by migrate.py - do not call create_all here
    # as it can conflict with manually added enum values
    yield


# ─────────────────────────── App ───────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-Tenant SaaS CRM Platform API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── Global exception handler (exposes real error messages) ──────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    print(f"UNHANDLED ERROR: {exc}\n{tb}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )

# ── Middleware ────────────────────────────────────────────────
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TenantIsolationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────
app.include_router(api_router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "app": settings.APP_NAME}


# ── Serve frontend static files ───────────────────────────────
import os

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
templates_path = os.path.join(frontend_path, "templates")
static_path = os.path.join(frontend_path, "static")

if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

if os.path.exists(templates_path):
    app.mount("/templates", StaticFiles(directory=templates_path, html=True), name="templates")

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(os.path.join(templates_path, "index.html"))
