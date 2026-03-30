"""
AIB OCR Subsystem — API v1 Router
Объединяет все эндпоинты
"""
from fastapi import APIRouter
from app.api.v1.endpoints import documents, tasks, health, auth

api_router = APIRouter()

api_router.include_router(health.router,    prefix="/health",    tags=["Health"])
api_router.include_router(auth.router,      prefix="/auth",      tags=["Auth"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(tasks.router,     prefix="/tasks",     tags=["Tasks"])
