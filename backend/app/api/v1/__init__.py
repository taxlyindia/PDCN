from fastapi import APIRouter
from app.api.v1.endpoints import auth, admin, tenant, pdcn, chat, reports, pricing, knowledge, platform_videos

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(tenant.router)
api_router.include_router(pdcn.router)
api_router.include_router(chat.router)
api_router.include_router(reports.router)
api_router.include_router(pricing.router)
api_router.include_router(knowledge.router)
api_router.include_router(platform_videos.router)
