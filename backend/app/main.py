import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import Scope

from app import auth
from app.api import batches, designer, drafts, health, jobs, labels, printers, printing, tokens
from app.api_v1 import create_v1_app
from app.config import Settings, get_settings
from app.db import create_engine, create_sessionmaker
from app.models import Printer
from app.schemas import UserOut
from app.services.batch_service import BatchRunner

log = logging.getLogger(__name__)


# Paths owned by the backend: when nothing serves them (e.g. the internal docs are disabled)
# they must be a plain 404, not the frontend's index.html.
BACKEND_PREFIXES = ("api/", "auth/", "docs/", "redoc/")
BACKEND_PATHS = ("docs", "redoc", "openapi.json")


class SPAStaticFiles(StaticFiles):
    """Serve the built frontend, falling back to index.html for client-side routes."""

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path.startswith(BACKEND_PREFIXES) or path in BACKEND_PATHS:
                raise
            return await super().get_response("index.html", scope)


async def seed_default_printer(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    if not settings.default_printer_host:
        return
    async with app.state.sessionmaker() as session:
        if await session.scalar(select(Printer.id).limit(1)) is not None:
            return
        session.add(
            Printer(
                name=settings.default_printer_name,
                host=settings.default_printer_host,
                port=settings.default_printer_port,
                dpi=settings.default_printer_dpi,
                is_default=True,
            )
        )
        await session.commit()
        log.info("Created default printer %s", settings.default_printer_host)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings.database_url)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.batch_runner = BatchRunner(app.state.sessionmaker, settings)
    await app.state.batch_runner.recover()
    await seed_default_printer(app)
    try:
        yield
    finally:
        await app.state.batch_runner.shutdown()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # The interactive docs of the internal (web UI) API are off unless asked for; the external
    # API documents itself at /api/v1/docs.
    docs = settings.enable_internal_docs
    app = FastAPI(
        title="Zebra Web",
        version="1.1.0",  # x-release-please-version
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.oauth = auth.create_oauth(settings)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="zebra_session",
        same_site="lax",
        https_only=settings.public_url.startswith("https://"),
        max_age=14 * 24 * 3600,
    )

    public = APIRouter(prefix="/api")
    public.add_api_route("/health", health.health, methods=["GET"], tags=["health"])
    app.include_router(public)

    protected = APIRouter(prefix="/api", dependencies=[Depends(auth.current_user)])
    protected.add_api_route(
        "/me", health.me, methods=["GET"], tags=["health"], response_model=UserOut
    )
    for module in (printers, printing, designer, labels, jobs, batches, drafts, tokens):
        protected.include_router(module.router)
    app.include_router(protected)
    app.include_router(auth.router)
    app.mount("/api/v1", create_v1_app(app))

    index = settings.static_dir / "index.html"
    if index.is_file():
        app.mount("/", SPAStaticFiles(directory=settings.static_dir, html=True), name="spa")
    return app


app = create_app()
