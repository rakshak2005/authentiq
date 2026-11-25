import os
import secrets
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="authentiq-pytest-"))

os.environ["AUTHENTIQ_ENVIRONMENT"] = "test"
os.environ["AUTHENTIQ_DEBUG"] = "false"
os.environ["AUTHENTIQ_SEED_DEMO"] = "false"
os.environ["AUTHENTIQ_SECRET_KEY"] = "authentiq-test-secret-key-0123456789abcdef"
os.environ["AUTHENTIQ_DATABASE_URL"] = f"sqlite:///{(TEST_ROOT / 'test.db').as_posix()}"
os.environ["AUTHENTIQ_STORAGE_DIR"] = str(TEST_ROOT / "storage")
os.environ["AUTHENTIQ_UPLOAD_DIR"] = str(TEST_ROOT / "storage" / "uploads")
os.environ["AUTHENTIQ_EVIDENCE_DIR"] = str(TEST_ROOT / "storage" / "evidence")
os.environ["AUTHENTIQ_LEDGER_FILE"] = str(TEST_ROOT / "storage" / "ledger.jsonl")
os.environ["AUTHENTIQ_LEDGER_MODE"] = "simulation"
os.environ["AUTHENTIQ_LOGIN_RATE_LIMIT"] = "1000"
os.environ["AUTHENTIQ_LOGIN_RATE_WINDOW_SECONDS"] = "60"
os.environ["AUTHENTIQ_REGISTRATION_RATE_LIMIT"] = "1000"
os.environ["AUTHENTIQ_REGISTRATION_RATE_WINDOW_SECONDS"] = "60"

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import engine
from app.main import app
from app.models import Base
from app.security.rate_limit import login_limiter, member_limiter, proof_limiter, register_limiter


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def client():
    assert TEST_ROOT.as_posix() in settings.database_url
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_state():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    settings.ledger_file.write_text("", encoding="utf-8")
    for limiter in (login_limiter, register_limiter, proof_limiter, member_limiter):
        limiter._events.clear()
    yield


@pytest.fixture
def user_factory(client):
    from tests.helpers import register_user

    created = []

    def factory(display_name="Test Creator", account_type="individual", organization_name=None):
        return register_user(
            client,
            display_name=display_name,
            account_type=account_type,
            organization_name=organization_name,
            created=created,
        )

    return factory


@pytest.fixture
def unique_email():
    return f"user-{secrets.token_hex(6)}@authentiq.dev"


def _freeze_clock(monkeypatch, fixed: datetime):
    """Patch ``datetime.now`` everywhere to always return ``fixed``.

    Patches the stdlib and every module that imported ``datetime`` by name,
    so registration timestamps, dashboard ``now``, and JWT token
    expiry/validation all share the same clock.
    """
    import datetime as dt_module

    class FrozenDateTime(dt_module.datetime):
        @classmethod
        def now(cls, tz=None):
            result = fixed
            if tz is not None:
                result = result.astimezone(tz)
            return result

    monkeypatch.setattr(dt_module, "datetime", FrozenDateTime)
    for mod in (
        "app.models.base",
        "app.core.clock",
        "app.security.crypto",
        "app.core.deps",
    ):
        monkeypatch.setattr(f"{mod}.datetime", FrozenDateTime)
    try:
        import jose.jwt

        monkeypatch.setattr("jose.jwt.datetime", FrozenDateTime)
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def fixed_clock(monkeypatch):
    """Freeze the wall clock to a deterministic UTC moment
    (2026-11-11 10:00 UTC, where UTC and UTC+05:30 agree on the date).
    """
    fixed = datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone.utc)
    _freeze_clock(monkeypatch, fixed)
    return fixed


@pytest.fixture
def dashboard_clock(monkeypatch):
    """Patch only ``reader_now`` for dashboard tests.

    Registration is created normally (real clock, valid JWT), then
    ``registered_at`` is overridden in the database. The dashboard's
    ``now`` is frozen so the heatmap window is deterministic.
    """
    import datetime as dt_module
    from datetime import datetime, timezone

    fixed = datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone.utc)

    class FrozenDateTime(dt_module.datetime):
        @classmethod
        def now(cls, tz=None):
            result = fixed
            if tz is not None:
                result = result.astimezone(tz)
            return result

    monkeypatch.setattr("app.core.clock.datetime", FrozenDateTime)
    return fixed
