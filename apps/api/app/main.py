from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.admin import router as admin_router
from app.api.auth import drop_stale_reader_cookie, router as auth_router
from app.api.deps import StaleReaderSession
from app.api.engagement import router as engagement_router, saved_router
from app.api.geo import router as geo_router
from app.api.admin_cases import router as admin_cases_router
from app.api.cases import router as cases_router
from app.api.health import router as health_router
from app.api.public import router as public_router
from app.api.transparency import router as transparency_router
from app.core.admin_secret import assert_admin_password
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging("api")
settings = get_settings()
assert_admin_password(settings.admin_password)


def create_app() -> FastAPI:
    application = FastAPI(title="Sin Línea API", version="0.1.0")

    @application.exception_handler(StaleReaderSession)
    async def drop_stale_reader(_request, _exc: StaleReaderSession) -> JSONResponse:
        response = JSONResponse({"detail": "No autenticado"}, status_code=401, headers={"Cache-Control": "private, no-store"})
        drop_stale_reader_cookie(response)
        return response

    @application.middleware("http")
    async def transparency_private(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/transparency"):
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
    application.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret,
        session_cookie="sl_admin",
        same_site="lax",
        https_only=settings.cookie_secure,
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
    application.include_router(auth_router)
    application.include_router(geo_router)
    application.include_router(engagement_router)
    application.include_router(saved_router)
    application.include_router(public_router)
    application.include_router(transparency_router)
    application.include_router(cases_router)
    application.include_router(admin_router)
    application.include_router(admin_cases_router)
    return application


app = create_app()
