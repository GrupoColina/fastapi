"""Routers da API administrativa do Studio."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.admin import api_keys, auth, datasources, endpoints, logs, projects, users

# Prefixo comum: /api/admin
admin_router = APIRouter(prefix="/api/admin")

admin_router.include_router(auth.router)
admin_router.include_router(users.router)
admin_router.include_router(projects.router)
admin_router.include_router(datasources.router)
admin_router.include_router(endpoints.router)
admin_router.include_router(api_keys.router)
admin_router.include_router(logs.router)

__all__ = ["admin_router"]
