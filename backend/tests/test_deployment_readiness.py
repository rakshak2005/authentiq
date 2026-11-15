"""
Deployment-readiness regression tests.

Covers:
- Secret key validation (rejects default in production, enforces min length)
- Demo mode (defaults off, rejected in production)
- Chain ID validation (refuses Polygon mainnet chainId 137)
- Ledger status endpoint shape
- Idempotent registration (no duplicate anchored tx)
"""

import pytest
from app.core.config import Settings, settings
from app.core.database import SessionLocal, engine
from app.ledger.blockchain import PolygonAdapter
from app.ledger.service import LedgerService
from app.ledger.simulation import LedgerUnavailable
from app.main import app
from app.models import Base, LedgerTransaction
from pydantic import ValidationError
from tests.helpers import register_user
from sqlalchemy import select


def _patch_chain_config(monkeypatch):
    monkeypatch.setattr(settings, "chain_rpc_url", "http://127.0.0.1:8545")
    monkeypatch.setattr(settings, "chain_private_key", "0x" + "01" * 32)
    monkeypatch.setattr(settings, "chain_contract_address", "0x" + "00" * 20)
    monkeypatch.setattr(settings, "chain_id", 80002)


# ---------------------------------------------------------------------------
# Secret key validation
# ---------------------------------------------------------------------------


def test_secret_key_rejects_default_in_production():
    """Production must not run with the default development secret."""
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            secret_key="authentiq-development-secret-change-me-0000000000000000",
        )


def test_secret_key_enforces_min_length():
    """Secret keys shorter than 32 characters are rejected."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", secret_key="short")


# ---------------------------------------------------------------------------
# Demo mode
# ---------------------------------------------------------------------------


def test_demo_mode_defaults_to_false():
    """demo_mode must default to False so production is not demo by accident."""
    assert Settings(_env_file=None).demo_mode is False


def test_demo_mode_rejected_in_production():
    with pytest.raises(ValueError, match="AUTHENTIQ_DEMO_MODE must be false"):
        Settings(_env_file=None, environment="production", demo_mode=True)


# ---------------------------------------------------------------------------
# Chain ID validation
# ---------------------------------------------------------------------------


def test_chain_id_validation_rejects_mainnet(monkeypatch):
    """Polygon adapter must refuse to connect to Polygon mainnet (chainId 137)."""
    _patch_chain_config(monkeypatch)
    from unittest.mock import MagicMock, patch

    class _FakeWeb3:
        def is_connected(self):
            return True

        @property
        def eth(self):
            return self._eth

        @eth.setter
        def eth(self, value):
            self._eth = value

        def to_checksum_address(self, addr):
            return addr

    class _FakeEth:
        def __init__(self):
            self.chain_id = 137  # Polygon mainnet

        def contract(self, address, abi):
            return MagicMock()

    fake_w3 = _FakeWeb3()
    fake_w3.eth = _FakeEth()
    with patch("app.ledger.blockchain.Web3", return_value=fake_w3), patch(
        "app.ledger.blockchain.Account"
    ), patch("app.ledger.blockchain.Web3.HTTPProvider"):
        with pytest.raises(LedgerUnavailable, match="does not match configured"):
            PolygonAdapter()


# ---------------------------------------------------------------------------
# Ledger status
# ---------------------------------------------------------------------------


def test_ledger_status_endpoint(client):
    """GET /api/ledger/status returns a consistent shape."""
    user = register_user(client, display_name="Ledger Status User")
    resp = client.get("/api/ledger/status", headers=user["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert "mode" in body
    assert body["mode"] in ("simulation", "polygon")


# ---------------------------------------------------------------------------
# Idempotent registration (no duplicate anchored tx)
# ---------------------------------------------------------------------------


def test_registration_idempotency_no_duplicate_tx():
    """Repeated registration with the same idempotency key yields one DB row."""
    Base.metadata.create_all(bind=engine)
    service = LedgerService()
    with SessionLocal() as db:
        service._record(
            db,
            tx_type="creation_registered",
            actor_id="user_1",
            entity_type="registration",
            entity_id="reg_idem",
            payload={"registration_id": "reg_idem"},
            idempotency_key="creation_registered:reg_idem",
        )
        db.commit()
        service._record(
            db,
            tx_type="creation_registered",
            actor_id="user_1",
            entity_type="registration",
            entity_id="reg_idem",
            payload={"registration_id": "reg_idem"},
            idempotency_key="creation_registered:reg_idem",
        )
        db.commit()
        rows = (
            db.execute(
                select(LedgerTransaction).where(
                    LedgerTransaction.idempotency_key == "creation_registered:reg_idem"
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
