from fastapi import APIRouter

from app.api.v1 import advisors, areas, auth, boards, calendly, chatbot, clients, dashboard, documents, docusign, health, merchants, notifications, onboarding_reminders, payments, portal, prospects, roles, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(advisors.router)
api_router.include_router(users.router)
api_router.include_router(areas.router)
api_router.include_router(merchants.router)
api_router.include_router(roles.router)
api_router.include_router(notifications.router)
api_router.include_router(clients.router)
api_router.include_router(prospects.router)
api_router.include_router(dashboard.router)
api_router.include_router(calendly.router)
api_router.include_router(docusign.router)
api_router.include_router(payments.router)
api_router.include_router(onboarding_reminders.router)
api_router.include_router(portal.router)
api_router.include_router(documents.router)
api_router.include_router(boards.router)
api_router.include_router(chatbot.router)
