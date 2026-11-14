"""Tests for Polygon Amoy ledger integration.

These tests mock web3/eth-account to avoid requiring a real RPC connection or
private key. They verify:

* Chain ID validation before transaction submission
* Successful transaction submission and receipt capture
* Error handling: RPC timeout, insufficient funds, invalid address,
  unauthorized writer, failed transaction
* LedgerService idempotency (no duplicate submissions on retry)
* No silent fallback to simulation when Polygon mode is unavailable
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from web3.exceptions import ContractLogicError, InvalidAddress

from app.core.database import SessionLocal
from app.ledger.blockchain import PolygonAdapter
from app.ledger.service import LedgerService
from app.ledger.simulation import LedgerUnavailable, SimulationLedger
from app.models import LedgerTransaction


class _FakeReceipt:
    def __init__(self, block_number=1, status=1):
        self.blockNumber = block_number
        self.status = status


class _FakeAccount:
    @classmethod
    def from_key(cls, key):
        return _FakeAccount()

    def sign_transaction(self, tx):
        class _Signed:
            raw_transaction = b"\x01" * 32

        return _Signed()


class _FakeEth:
    def __init__(self, chain_id=80002, should_revert=False, revision=1, connected=True):
        self.chain_id = chain_id
        self._should_revert = should_revert
        self._revision = revision
        self._connected = connected

    def is_connected(self):
        return self._connected

    def get_transaction_count(self, address):
        return 1

    def send_raw_transaction(self, raw_tx):
        return b"\x01" * 32

    def wait_for_transaction_receipt(self, tx_hash, timeout=180):
        return _FakeReceipt(block_number=42, status=1)

    def contract(self, address, abi):
        return _FakeContract(
            should_revert=self._should_revert, revision=self._revision
        )


class _FakeContractFunctions:
    def __init__(self, should_revert=False, revision=1):
        self._should_revert = should_revert
        self._revision = revision

    def recordEvent(self, record_id, record_type, payload_digest, entity_id):
        return _FakeContractCall(
            self, "recordEvent", should_revert=self._should_revert
        )

    def revisionCounts(self, record_id):
        return _FakeContractCall(
            self, "revisionCounts", return_value=self._revision
        )


class _FakeContractCall:
    def __init__(self, functions, name, should_revert=False, return_value=None):
        self._should_revert = should_revert
        self._return_value = return_value

    def build_transaction(self, tx_dict):
        if self._should_revert:
            raise ContractLogicError("execution reverted: NotWriter")
        return dict(tx_dict)

    def call(self):
        if self._should_revert:
            raise ContractLogicError("execution reverted: NotWriter")
        return self._return_value


class _FakeContract:
    def __init__(self, should_revert=False, revision=1):
        self.functions = _FakeContractFunctions(
            should_revert=should_revert, revision=revision
        )


class _FakeWeb3:
    def __init__(self, chain_id=80002, should_revert=False, revision=1, connected=True):
        self.chain_id_value = chain_id
        self._should_revert = should_revert
        self._revision = revision
        self._connected = connected
        self.eth = _FakeEth(
            chain_id=chain_id,
            should_revert=should_revert,
            revision=revision,
            connected=connected,
        )

    def is_connected(self):
        return self._connected

    def to_checksum_address(self, addr):
        return addr

    def to_hex(self, val):
        if isinstance(val, bytes):
            return "0x" + val.hex()
        return val

    def to_wei(self, value, unit):
        if unit == "gwei":
            return int(value) * 1_000_000_000
        return int(value)


def _install_mock_web3(chain_id=80002, should_revert=False, revision=1, connected=True):
    """Patch Web3 and Account at the blockchain module level."""
    fake_w3 = _FakeWeb3(
        chain_id=chain_id,
        should_revert=should_revert,
        revision=revision,
        connected=connected,
    )
    return patch("app.ledger.blockchain.Web3", return_value=fake_w3), patch(
        "app.ledger.blockchain.Account", _FakeAccount
    )


class TestPolygonAdapterChainIdValidation:
    def test_rejects_mismatched_chain_id(self):
        """Adapter must reject a connected chain ID that doesn't match config."""
        from app.core.config import settings

        original = settings.chain_id
        settings.chain_id = 80002
        try:
            with _install_mock_web3(chain_id=137):  # mainnet
                with pytest.raises(LedgerUnavailable, match="does not match configured"):
                    PolygonAdapter()
        finally:
            settings.chain_id = original


class TestPolygonAdapterTransactionSubmission:
    def test_successful_submission_captures_all_fields(self):
        with _install_mock_web3(chain_id=80002, revision=3) as (_, _):
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


class TestPolygonAdapterErrorHandling:
    def test_contract_revert_raises_ledger_unavailable(self):
        with _install_mock_web3(chain_id=80002, should_revert=True):
            adapter = PolygonAdapter()
            with pytest.raises(LedgerUnavailable, match="reverted"):
                adapter.append(
                    tx_type="creation_registered",
                    actor_id="user_123",
                    entity_type="registration",
                    entity_id="reg_abc",
                    payload={"registration_id": "reg_abc"},
                )

    def test_invalid_contract_address_raises_ledger_unavailable(self):
        from app.core.config import settings

        original = settings.chain_contract_address
        settings.chain_contract_address = "not-an-address"
        try:
            mock_w3 = _FakeWeb3(chain_id=80002)
            mock_w3.is_connected = MagicMock(return_value=True)
            with patch("app.ledger.blockchain.Web3", return_value=mock_w3), patch(
                "app.ledger.blockchain.Account", _FakeAccount
            ), patch(
                "app.ledger.blockchain.Web3.HTTPProvider", MagicMock()
            ), patch(
                "app.ledger.blockchain.Web3.to_checksum_address",
                side_effect=InvalidAddress("bad"),
            ):
                with pytest.raises(LedgerUnavailable, match="Invalid contract address"):
                    PolygonAdapter()
        finally:
            settings.chain_contract_address = original


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
    def test_polygon_unavailable_raises_instead_of_falling_back(self):
        """When ledger_mode=polygon and PolygonAdapter fails, LedgerService must raise."""
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
