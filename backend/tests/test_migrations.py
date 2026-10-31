import io

from alembic import command
from alembic.config import Config

from app.config import get_settings
from tests.conftest import BACKEND_DIR


def test_database_url_with_percent_encoded_password(monkeypatch):
    """ConfigParser interpolation must not choke on URL-encoded passwords."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://zebra:p%40ss%25@db:5432/zebra")
    get_settings.cache_clear()
    try:
        output = io.StringIO()
        config = Config(str(BACKEND_DIR / "alembic.ini"), stdout=output)
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        config.attributes["configure_logger"] = False
        command.upgrade(config, "head", sql=True)  # offline mode: renders SQL, no connection
        assert config.get_main_option("sqlalchemy.url") == (
            "postgresql+asyncpg://zebra:p%40ss%25@db:5432/zebra"
        )
    finally:
        get_settings.cache_clear()
