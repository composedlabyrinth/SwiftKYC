from fastapi import APIRouter
from app.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Health check")
async def health_check():
    return {
        "app": settings.APP_NAME,
        "status": "ok"
    }
