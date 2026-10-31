import io
import os
import socket
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import text

from app.config import Settings
from app.main import create_app
from app.models import ApiToken
from app.printer.emulator import PrinterEmulator
from app.tokens import generate_token

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://zebra:zebra@localhost:5432/zebra_test"
)


def make_settings(**overrides) -> Settings:
    values = {
        "database_url": TEST_DATABASE_URL,
        "auth_enabled": False,
        "printer_timeout": 1.0,
        "printer_settings_idle": 0.3,
        "static_dir": BACKEND_DIR / "no-static",
        "batch_chunk_size": 2,
        "session_secret": "test-secret-0123456789",
        "default_printer_host": "",
        # The emulator listens on a random loopback port.
        "printer_allow_loopback": True,
        "printer_allowed_ports": "1-65535",
    } | overrides
    return Settings(_env_file=None, **values)


def _migrate(url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def migrated_db() -> None:
    # Alembic's env.py uses asyncio.run(), so run it outside the test event loop.
    with ThreadPoolExecutor(1) as pool:
        pool.submit(_migrate, TEST_DATABASE_URL).result()


@pytest.fixture(scope="session")
async def app(migrated_db) -> AsyncIterator[FastAPI]:
    application = create_app(make_settings())
    async with LifespanManager(application):
        yield application


async def truncate(application: FastAPI) -> None:
    async with application.state.engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE print_jobs, print_batches, labels, printers, user_drafts, api_tokens "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    await truncate(app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    await app.state.batch_runner.shutdown()


@pytest.fixture
async def emulator() -> AsyncIterator[PrinterEmulator]:
    async with PrinterEmulator() as printer_emulator:
        yield printer_emulator


@pytest.fixture
def closed_port() -> int:
    """A local port with nothing listening on it."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def printer(client: httpx.AsyncClient, emulator: PrinterEmulator) -> dict:
    response = await client.post(
        "/api/printers",
        json={"name": "Emulator", "host": "127.0.0.1", "port": emulator.port, "dpi": 203},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def add_token(app: FastAPI, owner_sub: str, name: str = "Other") -> int:
    _, prefix, digest = generate_token()
    async with app.state.sessionmaker() as session:
        token = ApiToken(
            owner_sub=owner_sub,
            owner_identity=owner_sub,
            name=name,
            prefix=prefix,
            token_hash=digest,
        )
        session.add(token)
        await session.commit()
        return token.id


@pytest.fixture
async def api_token(client: httpx.AsyncClient) -> dict:
    """A token for the external API, created through the web UI's endpoint."""
    response = await client.post("/api/tokens", json={"name": "Inventory"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def api_headers(api_token: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token['token']}"}


def png_image(content: bytes) -> Image.Image:
    return Image.open(io.BytesIO(content)).convert("L")
