from fastapi import APIRouter

from app.api.routes import areas, auth, boards, clients, documents, health, notifications, portal, roles, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(areas.router)
api_router.include_router(roles.router)
api_router.include_router(notifications.router)
api_router.include_router(clients.router)
api_router.include_router(portal.router)
api_router.include_router(documents.router)
api_router.include_router(boards.router)
