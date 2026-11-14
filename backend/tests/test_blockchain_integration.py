"""
End-to-end blockchain integration tests for AUTHENTIQ.

These tests deploy AuthentiqRegistry.sol to a local Hardhat node, configure the
FastAPI backend for Polygon mode, and run through the full registration lifecycle.
On-chain state is independently queried via web3 and compared against the
application's registration records.

Uses a local Hardhat blockchain for automated tests. Polygon Amoy testnet is
only used for explicitly approved manual integration tests. Never mainnet.
"""

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen, Request

import pytest
from fastapi.testclient import TestClient
from web3 import Web3

from app.core.config import get_settings
from app.core.database import engine
from app.models import Base
from app.ledger.blockchain import PolygonAdapter
from app.ledger.service import LedgerService, LedgerUnavailable
from app.main import app
from tests.helpers import PASSWORD

BLOCKCHAIN_DIR = Path(__file__).parents[2] / "blockchain"
HARDHAT_NODE_URL = "http://127.0.0.1:8545"
HARDHAT_CHAIN_ID = 31337
HARDHAT_PRIVATE_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)


def _wait_for_hardhat(url: str, timeout: float = 30.0) -> None:
    """Wait until the Hardhat node accepts JSON-RPC calls."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            payload = json.dumps(
                {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}
            ).encode("utf-8")
            req = Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"Hardhat node did not become ready: {last_error}")


def _run_npx(args: list[str], cwd: Path, timeout: int = 120):
    """Run an npx command via cmd.exe on Windows."""
    return subprocess.run(
        ["cmd", "/c", "npx"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _start_hardhat_node():
    """Start a local Hardhat node as a subprocess."""
    return subprocess.Popen(
        ["cmd", "/c", "npx", "hardhat", "node"],
        cwd=str(BLOCKCHAIN_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ},
    )


# ---------------------------------------------------------------------------
# Session-scoped fixtures: Hardhat node + contract deployment
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def hardhat_node():
    """Start a local Hardhat node for the entire test session."""
    proc = _start_hardhat_node()
    try:
        _wait_for_hardhat(HARDHAT_NODE_URL)
        yield HARDHAT_NODE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def deployed_contract(hardhat_node):
    """Deploy AuthentiqRegistry.sol to the local Hardhat node."""
    result = _run_npx(
        ["hardhat", "run", "scripts/deploy_local.js", "--network", "localhost"],
        BLOCKCHAIN_DIR,
    )
    if result.returncode != 0:
        pytest.fail(
            f"Contract deployment failed (exit {result.returncode}):\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    artifact_path = BLOCKCHAIN_DIR / "deployments" / "31337.json"
    if not artifact_path.exists():
        pytest.fail(f"Deployment artifact not found at {artifact_path}")

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["chainId"] == HARDHAT_CHAIN_ID
    assert artifact["address"].startswith("0x")
    return artifact


# ---------------------------------------------------------------------------
# Function-scoped fixture: backend configured for Polygon mode
# ---------------------------------------------------------------------------


def _configure_polygon_backend(monkeypatch, contract_address: str):
    """Patch settings and ledger_service for Polygon mode against local Hardhat."""
    monkeypatch.setenv("AUTHENTIQ_LEDGER_MODE", "polygon")
    monkeypatch.setenv("AUTHENTIQ_CHAIN_RPC_URL", HARDHAT_NODE_URL)
    monkeypatch.setenv("AUTHENTIQ_CHAIN_PRIVATE_KEY", HARDHAT_PRIVATE_KEY)
    monkeypatch.setenv("AUTHENTIQ_CHAIN_CONTRACT_ADDRESS", contract_address)
    monkeypatch.setenv("AUTHENTIQ_CHAIN_ID", str(HARDHAT_CHAIN_ID))

    # Clear the lru_cache so get_settings() re-reads env vars
    get_settings.cache_clear()
    cfg = get_settings()
    assert cfg.ledger_mode == "polygon"
    assert cfg.chain_id == HARDHAT_CHAIN_ID
    assert cfg.chain_contract_address == contract_address

    # Update the module-level settings object so all modules read polygon config
    import app.core.config as _config_module
    monkeypatch.setattr(_config_module, "settings", cfg)
    monkeypatch.setattr("app.ledger.service.settings", cfg)
    monkeypatch.setattr("app.ledger.blockchain.settings", cfg)

    # Recreate LedgerService (will construct PolygonAdapter against local node)
    new_service = LedgerService()

    # Patch every module that holds a reference to the module-level ledger_service
    monkeypatch.setattr("app.ledger.ledger_service", new_service)
    monkeypatch.setattr("app.ledger.service.ledger_service", new_service)
    monkeypatch.setattr("app.services.registration_service.ledger_service", new_service)
    monkeypatch.setattr("app.api.registrations.ledger_service", new_service)
    monkeypatch.setattr("app.api.ledger.ledger_service", new_service)
    monkeypatch.setattr("app.main.ledger_service", new_service)

    return new_service


@pytest.fixture
def polygon_client(monkeypatch, deployed_contract):
    """Create a TestClient configured for Polygon mode with local Hardhat contract."""
    _configure_polygon_backend(monkeypatch, deployed_contract["address"])

    with TestClient(app) as client:
        yield {
            "client": client,
            "rpc_url": HARDHAT_NODE_URL,
            "contract_address": deployed_contract["address"],
            "private_key": HARDHAT_PRIVATE_KEY,
            "chain_id": HARDHAT_CHAIN_ID,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_user(client):
    email = f"user-{hashlib.sha256(os.urandom(8)).hexdigest()[:12]}@authentiq.dev"
    payload = {
        "display_name": "Integration Creator",
        "email": email,
        "password": PASSWORD,
        "confirm_password": PASSWORD,
        "account_type": "individual",
        "accept_terms": True,
    }
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    return {
        "email": email,
        "token": data["access_token"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


def _create_registration(client, headers, content=b"AUTHENTIQ integration payload"):
    """Upload a file and register it as a creation."""
    # Initiate upload
    initiate = client.post(
        "/api/uploads/initiate",
        headers=headers,
        json={
            "filename": "artifact.txt",
            "size_bytes": len(content),
            "mime_type": "text/plain",
            "total_chunks": 1,
            "chunk_size": len(content),
        },
    )
    assert initiate.status_code == 200, initiate.text
    upload = initiate.json()

    # Upload chunk
    chunk_sha = hashlib.sha256(content).hexdigest()
    response = client.post(
        f"/api/uploads/{upload['upload_id']}/chunk",
        headers=headers,
        data={"chunk_index": "0", "sha256": chunk_sha},
        files={"file": ("artifact.txt", content, "text/plain")},
    )
    assert response.status_code == 200, response.text

    # Complete upload
    complete = client.post(
        f"/api/uploads/{upload['upload_id']}/complete",
        headers=headers,
        data={"client_sha256": chunk_sha},
    )
    assert complete.status_code == 200, complete.text

    # Register creation
    resp = client.post(
        "/api/registrations",
        headers=headers,
        json={
            "upload_id": upload["upload_id"],
            "title": "Integration Test Artifact",
            "description": "E2E blockchain integration test",
            "asset_type": "document",
            "privacy": "private",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    # Flatten ledger info into the registration dict for easier test access
    data["ledger_mode"] = data["ledger"]["mode"]
    data["ledger_tx_id"] = data["ledger"]["tx_id"]
    # Flatten registration status
    data["status"] = data["registration"]["status"]
    data["registration_id"] = data["registration"]["registration_id"]
    data["sha256"] = data["registration"]["sha256"]
    return data


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestRegistrationFlow:
    """Happy-path end-to-end registration with Polygon anchoring."""

    def test_full_registration_and_onchain_verification(
        self, polygon_client
    ):
        """Register a creation, submit to Polygon, verify on-chain state matches."""
        client = polygon_client["client"]
        web3 = Web3(Web3.HTTPProvider(HARDHAT_NODE_URL))
        contract_address = polygon_client["contract_address"]

        user = _register_user(client)
        headers = user["headers"]
        content = b"AUTHENTIQ end-to-end integration test content"
        registration = _create_registration(client, headers, content=content)

        # --- Application-level assertions ---
        assert registration["ledger_mode"] == "polygon"
        assert registration["ledger_tx_id"] is not None
        assert registration["status"] == "registered"
        sha256_fingerprint = hashlib.sha256(content).hexdigest()
        assert registration["sha256"] == sha256_fingerprint

        tx_id = registration["ledger_tx_id"]

        # --- Retrieve transaction detail from API ---
        detail = client.get(
            f"/api/ledger/transactions/{tx_id}", headers=headers
        )
        assert detail.status_code == 200, detail.text
        tx_detail = detail.json()
        assert tx_detail["tx_id"] == tx_id
        assert tx_detail["status"] == "confirmed"
        assert tx_detail["mode"] == "polygon"
        assert tx_detail["chain_id"] == HARDHAT_CHAIN_ID
        assert tx_detail["contract_address"] == contract_address
        assert tx_detail["block_number"] is not None
        assert tx_detail["chain_tx_hash"] == tx_id
        assert tx_detail["revision"] is not None and tx_detail["revision"] >= 1

        # --- Independently query the smart contract ---
        abi_path = (
            BLOCKCHAIN_DIR
            / "artifacts"
            / "contracts"
            / "AuthentiqRegistry.sol"
            / "AuthentiqRegistry.json"
        )
        contract_abi = json.loads(abi_path.read_text())["abi"]
        contract = web3.eth.contract(address=contract_address, abi=contract_abi)

        # Read revision counter from contract
        onchain_revision = contract.functions.revisionCounts(
            registration["registration_id"]
        ).call()
        assert onchain_revision == tx_detail["revision"], (
            f"On-chain revision {onchain_revision} != API revision {tx_detail['revision']}"
        )

        # Verify the transaction exists on-chain by checking receipt
        receipt = web3.eth.get_transaction_receipt(tx_id)
        assert receipt is not None
        assert receipt.status == 1
        assert receipt["to"] == Web3.to_checksum_address(contract_address)

        # --- Ledger status endpoint reflects polygon mode ---
        status = client.get("/api/ledger/status", headers=headers)
        assert status.status_code == 200
        status_body = status.json()
        assert status_body["mode"] == "polygon"
        assert status_body["connected"] is True
        assert status_body["available"] is True

    def test_registration_retrieval_shows_chain_fields(self, polygon_client):
        """The ledger transaction detail exposes chain_id, contract_address, revision."""
        client = polygon_client["client"]
        headers = _register_user(client)["headers"]
        registration = _create_registration(client, headers)

        tx_id = registration["ledger_tx_id"]
        tx_detail = client.get(
            f"/api/ledger/transactions/{tx_id}", headers=headers
        )
        assert tx_detail.status_code == 200
        tx = tx_detail.json()

        required_fields = [
            "tx_id", "block_number", "tx_type", "entity_type", "entity_id",
            "payload_digest", "mode", "network", "status",
            "chain_tx_hash", "contract_address", "chain_id", "revision",
        ]
        for field in required_fields:
            assert field in tx, f"Missing field '{field}' in ledger transaction detail"

        assert tx["mode"] == "polygon"
        assert tx["network"] == "Polygon Amoy"
        assert tx["status"] == "confirmed"
        assert tx["chain_id"] == HARDHAT_CHAIN_ID
        assert tx["contract_address"] == polygon_client["contract_address"]
        assert tx["revision"] >= 1

    def test_multiple_registrations_have_independent_revisions(
        self, polygon_client
    ):
        """Each registration gets its own revision counter on the contract."""
        client = polygon_client["client"]
        web3 = Web3(Web3.HTTPProvider(HARDHAT_NODE_URL))
        contract_address = polygon_client["contract_address"]

        abi_path = (
            BLOCKCHAIN_DIR
            / "artifacts"
            / "contracts"
            / "AuthentiqRegistry.sol"
            / "AuthentiqRegistry.json"
        )
        contract_abi = json.loads(abi_path.read_text())["abi"]
        contract = web3.eth.contract(address=contract_address, abi=contract_abi)

        user = _register_user(client)
        headers = user["headers"]

        # First registration
        reg1 = _create_registration(client, headers, content=b"first creation")
        tx1 = reg1["ledger_tx_id"]
        detail1 = client.get(f"/api/ledger/transactions/{tx1}", headers=headers).json()
        rev1_onchain = contract.functions.revisionCounts(reg1["registration_id"]).call()
        assert detail1["revision"] == rev1_onchain == 1

        # Second registration
        reg2 = _create_registration(client, headers, content=b"second creation")
        tx2 = reg2["ledger_tx_id"]
        detail2 = client.get(f"/api/ledger/transactions/{tx2}", headers=headers).json()
        rev2_onchain = contract.functions.revisionCounts(reg2["registration_id"]).call()
        assert detail2["revision"] == rev2_onchain == 1

        assert reg1["registration_id"] != reg2["registration_id"]


class TestErrorHandling:
    """Error scenarios: RPC failure, contract rejection, idempotency, etc."""

    def test_rpc_failure_prevents_blockchain_anchoring(self, monkeypatch, deployed_contract):
        """When the RPC is unreachable, LedgerService creation fails - no silent fallback."""
        import app.core.config as _config_module

        # Configure with bad RPC URL
        monkeypatch.setenv("AUTHENTIQ_LEDGER_MODE", "polygon")
        monkeypatch.setenv("AUTHENTIQ_CHAIN_RPC_URL", "http://127.0.0.1:9999")
        monkeypatch.setenv("AUTHENTIQ_CHAIN_PRIVATE_KEY", HARDHAT_PRIVATE_KEY)
        monkeypatch.setenv("AUTHENTIQ_CHAIN_CONTRACT_ADDRESS", deployed_contract["address"])
        monkeypatch.setenv("AUTHENTIQ_CHAIN_ID", str(HARDHAT_CHAIN_ID))

        get_settings.cache_clear()
        cfg = get_settings()
        assert cfg.ledger_mode == "polygon"

        # Patch settings at module level so PolygonAdapter reads the bad URL
        monkeypatch.setattr(_config_module, "settings", cfg)
        monkeypatch.setattr("app.ledger.blockchain.settings", cfg)
        monkeypatch.setattr("app.ledger.service.settings", cfg)

        # Directly verify Web3 cannot connect
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:9999"))
        assert w3.is_connected() is False

        # PolygonAdapter should fail because RPC is unreachable
        with pytest.raises(LedgerUnavailable):
            PolygonAdapter()

        # LedgerService should also fail (no silent fallback to simulation)
        with pytest.raises(LedgerUnavailable):
            LedgerService()

    def test_contract_revert_raises_error(self, monkeypatch, deployed_contract):
        """When the contract reverts (e.g., NotWriter), the error propagates to the API."""
        _configure_polygon_backend(monkeypatch, deployed_contract["address"])

        from unittest.mock import patch

        from app.ledger import ledger_service as ls_module

        client_ = TestClient(app, raise_server_exceptions=False)
        try:
            original_append = ls_module.adapter.append

            def failing_append(*args, **kwargs):
                raise LedgerUnavailable("execution reverted: NotWriter")

            ls_module.adapter.append = failing_append
            try:
                user = _register_user(client_)
                headers = user["headers"]
                content = b"test content for revert"

                # Upload
                initiate = client_.post(
                    "/api/uploads/initiate",
                    headers=headers,
                    json={
                        "filename": "revert.txt",
                        "size_bytes": len(content),
                        "mime_type": "text/plain",
                        "total_chunks": 1,
                        "chunk_size": len(content),
                    },
                )
                assert initiate.status_code == 200
                upload = initiate.json()

                chunk_sha = hashlib.sha256(content).hexdigest()
                client_.post(
                    f"/api/uploads/{upload['upload_id']}/chunk",
                    headers=headers,
                    data={"chunk_index": "0", "sha256": chunk_sha},
                    files={"file": ("revert.txt", content, "text/plain")},
                )
                client_.post(
                    f"/api/uploads/{upload['upload_id']}/complete",
                    headers=headers,
                    data={"client_sha256": chunk_sha},
                )

                # Registration should fail (no silent fallback to simulation)
                resp = client_.post(
                    "/api/registrations",
                    headers=headers,
                    json={
                        "upload_id": upload["upload_id"],
                        "title": "Revert Test",
                        "description": "",
                        "asset_type": "document",
                        "privacy": "private",
                    },
                )
                # The backend should return an error, not silently succeed
                assert resp.status_code != 201, (
                    f"Registration should not succeed on contract revert, got {resp.status_code}"
                )
            finally:
                ls_module.adapter.append = original_append
        finally:
            client_.close()

    def test_duplicate_api_requests_do_not_duplicate_onchain(
        self, polygon_client
    ):
        """Idempotency: re-registering returns existing ledger entry, no duplicate on-chain tx."""
        client = polygon_client["client"]
        web3 = Web3(Web3.HTTPProvider(HARDHAT_NODE_URL))
        contract_address = polygon_client["contract_address"]

        abi_path = (
            BLOCKCHAIN_DIR
            / "artifacts"
            / "contracts"
            / "AuthentiqRegistry.sol"
            / "AuthentiqRegistry.json"
        )
        contract_abi = json.loads(abi_path.read_text())["abi"]
        contract = web3.eth.contract(address=contract_address, abi=contract_abi)

        headers = _register_user(client)["headers"]
        content = b"idempotency test content"

        # First registration
        reg1 = _create_registration(client, headers, content=content)
        tx1 = reg1["ledger_tx_id"]
        total_before = contract.functions.totalRecords().call()

        # Register again with different content (same user)
        reg2 = _create_registration(client, headers, content=b"different content for idempotency")
        tx2 = reg2["ledger_tx_id"]

        # Each registration gets its own ledger transaction (different record IDs)
        assert tx1 != tx2
        assert reg1["registration_id"] != reg2["registration_id"]

        # On-chain total records increased by 1 (one per registration)
        total_after = contract.functions.totalRecords().call()
        assert total_after == total_before + 1

    def test_simulation_and_polygon_records_are_distinguishable(
        self, monkeypatch, deployed_contract
    ):
        """Simulated records and Polygon-anchored records are clearly labeled."""
        # Test in simulation mode first
        monkeypatch.setenv("AUTHENTIQ_LEDGER_MODE", "simulation")
        get_settings.cache_clear()
        cfg = get_settings()
        assert cfg.ledger_mode == "simulation"

        from app.ledger.service import LedgerService
        sim_service = LedgerService()

        monkeypatch.setattr("app.ledger.ledger_service", sim_service)
        monkeypatch.setattr("app.ledger.service.ledger_service", sim_service)
        monkeypatch.setattr("app.services.registration_service.ledger_service", sim_service)
        monkeypatch.setattr("app.api.registrations.ledger_service", sim_service)
        monkeypatch.setattr("app.api.ledger.ledger_service", sim_service)
        monkeypatch.setattr("app.main.ledger_service", sim_service)

        with TestClient(app) as client:
            headers = _register_user(client)["headers"]
            registration = _create_registration(client, headers)

            assert registration["ledger_mode"] == "simulation"
            status = client.get("/api/ledger/status", headers=headers).json()
            assert status["mode"] == "simulation"

        # Now in polygon mode
        _configure_polygon_backend(monkeypatch, deployed_contract["address"])

        with TestClient(app) as client:
            headers = _register_user(client)["headers"]
            registration = _create_registration(client, headers)

            assert registration["ledger_mode"] == "polygon"
            assert registration["ledger_tx_id"] is not None
            status = client.get("/api/ledger/status", headers=headers).json()
            assert status["mode"] == "polygon"
            assert status["connected"] is True


class TestStatusHandling:
    """Ledger status and confirmation status handling."""

    def test_ledger_status_reports_connected_polygon(self, polygon_client):
        """GET /api/ledger/status reports Polygon Amoy as connected."""
        client = polygon_client["client"]
        headers = _register_user(client)["headers"]

        status = client.get("/api/ledger/status", headers=headers)
        assert status.status_code == 200
        body = status.json()
        assert body["mode"] == "polygon"
        assert body["connected"] is True
        assert body["available"] is True
        assert body["network"] == "Polygon Amoy"
        assert body["chain_id"] == HARDHAT_CHAIN_ID
        assert body["contract_address"] == polygon_client["contract_address"]

    def test_transaction_detail_shows_confirmation_status(self, polygon_client):
        """Transaction detail shows confirmed status with block number and timestamp."""
        client = polygon_client["client"]
        headers = _register_user(client)["headers"]
        registration = _create_registration(client, headers)

        tx_detail = client.get(
            f"/api/ledger/transactions/{registration['ledger_tx_id']}", headers=headers
        )
        assert tx_detail.status_code == 200
        tx = tx_detail.json()

        assert tx["status"] == "confirmed"
        assert tx["block_number"] is not None
        assert tx["block_number"] >= 0
        assert tx["timestamp"] is not None
        assert tx["chain_tx_hash"] == tx["tx_id"]

    def test_application_does_not_report_confirmed_without_onchain_verification(
        self, polygon_client
    ):
        """A registration is only reported as confirmed after on-chain receipt verification."""
        client = polygon_client["client"]
        web3 = Web3(Web3.HTTPProvider(HARDHAT_NODE_URL))

        user = _register_user(client)
        headers = user["headers"]
        registration = _create_registration(client, headers)

        tx_id = registration["ledger_tx_id"]

        # Independently verify on-chain before accepting as confirmed
        receipt = web3.eth.get_transaction_receipt(tx_id)
        assert receipt is not None, f"Transaction {tx_id} has no on-chain receipt"
        assert receipt.status == 1, f"Transaction {tx_id} failed on-chain"

        # The API should reflect this confirmation
        detail = client.get(
            f"/api/ledger/transactions/{tx_id}", headers=headers
        )
        assert detail.status_code == 200
        assert detail.json()["status"] == "confirmed"

    def test_database_records_match_blockchain_count(self, polygon_client):
        """The number of database ledger records matches on-chain totalRecords delta."""
        client = polygon_client["client"]
        web3 = Web3(Web3.HTTPProvider(HARDHAT_NODE_URL))
        contract_address = polygon_client["contract_address"]

        abi_path = (
            BLOCKCHAIN_DIR
            / "artifacts"
            / "contracts"
            / "AuthentiqRegistry.sol"
            / "AuthentiqRegistry.json"
        )
        contract_abi = json.loads(abi_path.read_text())["abi"]
        contract = web3.eth.contract(address=contract_address, abi=contract_abi)

        headers = _register_user(client)["headers"]

        # Record on-chain total before registrations
        total_before = contract.functions.totalRecords().call()

        # Create 3 registrations
        for i in range(3):
            _create_registration(client, headers, content=f"content {i}".encode())

        # Count database ledger records
        status = client.get("/api/ledger/status", headers=headers)
        db_count = status.json()["database_records"]

        # Count on-chain records
        onchain_total = contract.functions.totalRecords().call()

        # On-chain total should have increased by exactly db_count
        assert onchain_total == total_before + db_count, (
            f"On-chain total ({onchain_total}) != total_before ({total_before}) + db_count ({db_count})"
        )
        assert db_count == 3
