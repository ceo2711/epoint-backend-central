import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.validation_errors import humanize_validation_errors

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Hace visibles en consola los logs INFO de la app (recordatorios, dry run, etc.)."""
    app_logger = logging.getLogger("app")
    if app_logger.level == logging.NOTSET:
        app_logger.setLevel(logging.INFO)
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s — %(message)s"))
        app_logger.addHandler(handler)
    app_logger.propagate = False


_configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    stop_reminders = None
    from app.workers.inline_scheduler import start_onboarding_reminder_scheduler

    stop_reminders = start_onboarding_reminder_scheduler(settings)
    if stop_reminders is not None:
        logger.info(
            "Scheduler de recordatorios en la API — cada %s min",
            settings.onboarding_reminder_interval_minutes,
        )
    yield
    from app.services.notifications.hub import notification_hub

    notification_hub.close_all()
    if stop_reminders is not None:
        from app.workers.inline_scheduler import stop_onboarding_reminder_scheduler

        stop_onboarding_reminder_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="API REST del CRM ePoint — onboarding de clientes",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": humanize_validation_errors(exc.errors())},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Error no controlado en la API")
        detail = str(exc) if settings.debug else "Error interno del servidor"
        return JSONResponse(status_code=500, content={"detail": detail})

    return app


app = create_app()
