from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.public import router as public_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging("api")
settings = get_settings()


def create_app() -> FastAPI:
    application = FastAPI(title="Sin Línea API", version="0.1.0")
    application.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret,
        session_cookie="sl_admin",
        same_site="lax",
        https_only=False,
        max_age=60 * 60 * 12,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
    application.include_router(public_router)
    application.include_router(admin_router)
    return application


app = create_app()
