"""Tests for Polygon Amoy ledger integration.

These tests mock web3/eth-account to avoid requiring a real RPC connection or
private key. They verify:

* Chain ID validation before transaction submission
* Successful transaction submission and receipt capture
* Error handling: contract revert, invalid contract address
* LedgerService idempotency (no duplicate submissions on retry)
* No silent fallback to simulation when Polygon mode is unavailable
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from web3.exceptions import ContractLogicError, InvalidAddress

from app.core.config import settings
from app.core.database import SessionLocal
from app.ledger.blockchain import PolygonAdapter
from app.ledger.service import LedgerService
from app.ledger.simulation import LedgerUnavailable, SimulationLedger
from app.models import LedgerTransaction


def _patch_chain_config(monkeypatch):
    """Patch required chain configuration on the settings singleton."""
    monkeypatch.setattr(settings, "chain_rpc_url", "http://localhost:8545")
    monkeypatch.setattr(settings, "chain_private_key", "0x" + "01" * 32)
    monkeypatch.setattr(settings, "chain_contract_address", "0x" + "00" * 20)
    monkeypatch.setattr(settings, "chain_id", 80002)


class _FakeAccount:
    address = "0x" + "ab" * 20

    @classmethod
    def from_key(cls, key):
        return _FakeAccount()

    def sign_transaction(self, tx):
        class _Signed:
            raw_transaction = b"\x01" * 32

        return _Signed()


def _make_mock_web3(chain_id=80002, receipt_status=1, should_revert=False, revision=3):
    """Build a MagicMock web3 instance configured for PolygonAdapter."""
    w3 = MagicMock()
    w3.is_connected.return_value = True
    w3.eth.chain_id = chain_id
    w3.eth.get_transaction_count.return_value = 1
    w3.eth.send_raw_transaction.return_value = b"\x01" * 32
    w3.eth.wait_for_transaction_receipt.return_value = MagicMock(
        blockNumber=42, status=receipt_status
    )
    w3.to_checksum_address.side_effect = lambda a: a
    w3.to_hex.side_effect = lambda b: "0x" + b.hex() if isinstance(b, bytes) else b
    w3.to_wei.side_effect = lambda v, unit: int(v) * 1_000_000_000 if unit == "gwei" else int(v)

    # Mock contract
    contract = MagicMock()
    contract.functions.revisionCounts.return_value.call.return_value = revision

    record_event_call = contract.functions.recordEvent.return_value
    if should_revert:
        record_event_call.build_transaction.side_effect = ContractLogicError(
            "execution reverted: NotWriter"
        )
    else:
        record_event_call.build_transaction.return_value = {}

    w3.eth.contract.return_value = contract

    # Mock account
    account = _FakeAccount()

    return w3, account, contract


class TestPolygonAdapterChainIdValidation:
    def test_rejects_mismatched_chain_id(self, monkeypatch):
        """Adapter must reject a connected chain ID that doesn't match config."""
        _patch_chain_config(monkeypatch)
        monkeypatch.setattr(settings, "chain_id", 80002)
        w3, account, _ = _make_mock_web3(chain_id=137)  # mainnet
        with patch("app.ledger.blockchain.Web3", return_value=w3), patch(
            "app.ledger.blockchain.Account", _FakeAccount
        ), patch("app.ledger.blockchain.Web3.HTTPProvider", MagicMock()):
            with pytest.raises(LedgerUnavailable, match="does not match configured"):
                PolygonAdapter()


class TestPolygonAdapterTransactionSubmission:
    def test_successful_submission_captures_all_fields(self, monkeypatch):
        _patch_chain_config(monkeypatch)
        w3, account, contract = _make_mock_web3(chain_id=80002, revision=3)
        with patch("app.ledger.blockchain.Web3", return_value=w3), patch(
            "app.ledger.blockchain.Account", _FakeAccount
        ), patch("app.ledger.blockchain.Web3.HTTPProvider", MagicMock()):
            adapter = PolygonAdapter()
            result = adapter.append(
                tx_type="creation_registered",
                actor_id="user_123",
                entity_type="registration",
                entity_id="reg_abc",
                payload={"registration_id": "reg_abc", "fingerprint": "a" * 64},
            )

            assert result["tx_id"] == "0x" + "01" * 32
            assert result["block_number"] == 42
            assert result["status"] == "confirmed"
            assert result["chain_tx_hash"] == result["tx_id"]
            assert result["contract_address"] == "0x" + "00" * 20
            assert result["chain_id"] == 80002
            assert result["revision"] == 3
            assert result["mode"] == "polygon"
            assert result["network"] == "Polygon Amoy"
            assert result["entity_id"] == "reg_abc"
            assert result["tx_type"] == "creation_registered"
            assert "payload_digest" in result

            # Verify recordEvent was called with correct args
            contract.functions.recordEvent.assert_called_once_with(
                "reg_abc", "creation_registered", result["payload_digest"], "reg_abc"
            )


class TestPolygonAdapterErrorHandling:
    def test_contract_revert_raises_ledger_unavailable(self, monkeypatch):
        _patch_chain_config(monkeypatch)
        w3, _, _ = _make_mock_web3(chain_id=80002, should_revert=True)
        with patch("app.ledger.blockchain.Web3", return_value=w3), patch(
            "app.ledger.blockchain.Account", _FakeAccount
        ), patch("app.ledger.blockchain.Web3.HTTPProvider", MagicMock()):
            adapter = PolygonAdapter()
            with pytest.raises(LedgerUnavailable, match="reverted"):
                adapter.append(
                    tx_type="creation_registered",
                    actor_id="user_123",
                    entity_type="registration",
                    entity_id="reg_abc",
                    payload={"registration_id": "reg_abc"},
                )

    def test_invalid_contract_address_raises_ledger_unavailable(self, monkeypatch):
        _patch_chain_config(monkeypatch)
        w3 = MagicMock()
        w3.is_connected.return_value = True
        w3.eth.chain_id = 80002
        w3.to_checksum_address.side_effect = InvalidAddress("bad address")
        with patch("app.ledger.blockchain.Web3", return_value=w3), patch(
            "app.ledger.blockchain.Account", _FakeAccount
        ), patch("app.ledger.blockchain.Web3.HTTPProvider", MagicMock()):
            with pytest.raises(LedgerUnavailable, match="Invalid contract address"):
                PolygonAdapter()


class TestLedgerServiceIdempotency:
    def test_duplicate_submission_returns_existing_transaction(self):
        """Repeated calls with the same idempotency key return the same DB row."""
        from app.core.config import settings

        original_mode = settings.ledger_mode
        settings.ledger_mode = "simulation"
        try:
            service = LedgerService()

            with SessionLocal() as db:
                # First call
                tx1 = service._record(
                    db,
                    tx_type="creation_registered",
                    actor_id="user_1",
                    entity_type="registration",
                    entity_id="reg_1",
                    payload={"registration_id": "reg_1"},
                    idempotency_key="creation_registered:reg_1",
                )
                db.commit()

                # Second call with same idempotency key - should return existing row
                tx2 = service._record(
                    db,
                    tx_type="creation_registered",
                    actor_id="user_1",
                    entity_type="registration",
                    entity_id="reg_1",
                    payload={"registration_id": "reg_1"},
                    idempotency_key="creation_registered:reg_1",
                )

                assert tx1.id == tx2.id
                assert tx1.tx_id == tx2.tx_id

                # Verify only one row exists in the database
                rows = (
                    db.execute(
                        select(LedgerTransaction).where(
                            LedgerTransaction.idempotency_key
                            == "creation_registered:reg_1"
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(rows) == 1
        finally:
            settings.ledger_mode = original_mode


class TestLedgerServiceNoSilentFallback:
    def test_polygon_unavailable_raises_instead_of_falling_back(self, monkeypatch):
        """When ledger_mode=polygon and PolygonAdapter fails, LedgerService must raise."""
        _patch_chain_config(monkeypatch)
        from app.core.config import settings

        original_mode = settings.ledger_mode
        settings.ledger_mode = "polygon"
        try:
            with patch(
                "app.ledger.blockchain.PolygonAdapter.__init__",
                side_effect=LedgerUnavailable("RPC unreachable"),
            ):
                with pytest.raises(LedgerUnavailable, match="RPC unreachable"):
                    LedgerService()
        finally:
            settings.ledger_mode = original_mode
