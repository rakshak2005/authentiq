# AUTHENTIQ Blockchain Integration Testing

## Overview

This document describes the end-to-end blockchain integration test suite for AUTHENTIQ.
The tests deploy `AuthentiqRegistry.sol` to a local Hardhat node, configure the FastAPI
backend for Polygon mode, and run through the full registration lifecycle with
independent on-chain verification.

**Network policy:** Local Hardhat blockchain for automated tests. Polygon Amoy testnet
only for explicitly approved manual integration tests. **Never Polygon mainnet.**

## Test Suite

**File:** `backend/tests/test_blockchain_integration.py`

**Test count:** 11 tests, all passing.

**Prerequisites:**
- Node.js with Hardhat (`blockchain/node_modules/`)
- Python with `web3` and `eth-account` (`backend/.venv/`)
- Compiled contract artifacts (`blockchain/artifacts/`)

## Test Categories

### 1. Registration Flow (TestRegistrationFlow)

| Test | What it verifies |
|---|---|
| `test_full_registration_and_onchain_verification` | Full E2E flow: register creation → submit to Polygon → verify on-chain receipt → compare revision counter → check ledger status endpoint |
| `test_registration_retrieval_shows_chain_fields` | Ledger transaction detail exposes `tx_id`, `block_number`, `contract_address`, `chain_id`, `revision`, `mode`, `network`, `status`, `chain_tx_hash`, `payload_digest` |
| `test_multiple_registrations_have_independent_revisions` | Each registration gets its own `revisionCounts` entry on the contract; revision counters are independent per record ID |

### 2. Error Handling (TestErrorHandling)

| Test | What it verifies |
|---|---|
| `test_rpc_failure_prevents_blockchain_anchoring` | Unreachable RPC → `PolygonAdapter` raises `LedgerUnavailable` → `LedgerService` raises `LedgerUnavailable` — no silent fallback to simulation |
| `test_contract_revert_raises_error` | Contract revert (e.g. `NotWriter`) → error propagates to API → registration does not succeed |
| `test_duplicate_api_requests_do_not_duplicate_onchain` | Each registration creates exactly one on-chain `recordEvent`; `totalRecords` increases by exactly 1 per registration |
| `test_simulation_and_polygon_records_are_distinguishable` | Simulation mode records show `mode: "simulation"`; Polygon mode records show `mode: "polygon"` — records are clearly distinguishable |

### 3. Status Handling (TestStatusHandling)

| Test | What it verifies |
|---|---|
| `test_ledger_status_reports_connected_polygon` | `GET /api/ledger/status` returns `mode: "polygon"`, `connected: true`, `available: true`, correct `chain_id` and `contract_address` |
| `test_transaction_detail_shows_confirmation_status` | Transaction detail shows `status: "confirmed"`, `block_number`, `timestamp`, `chain_tx_hash == tx_id` |
| `test_application_does_not_report_confirmed_without_onchain_verification` | Registration is only reported as confirmed after independently verifying the on-chain transaction receipt via `web3.eth.get_transaction_receipt()` |
| `test_database_records_match_blockchain_count` | Database `LedgerTransaction` count matches on-chain `totalRecords()` delta — no missing or duplicate anchors |

## Workflow Tested

Each happy-path test exercises this complete workflow:

1. **Register a new digital creation** via `POST /api/registrations` (file upload → registration)
2. **Generate canonical SHA-256 fingerprint** of the file content
3. **Create ledger payload digest** via `canonical_json(payload)` → `sha256()`
4. **Submit event to Polygon Amoy registry** via `contract.recordEvent(recordId, recordType, payloadDigest, entityId)`
5. **Wait for transaction confirmation** via `web3.eth.wait_for_transaction_receipt()`
6. **Persist transaction receipt** — `LedgerTransaction` row stores `tx_id`, `chain_tx_hash`, `contract_address`, `chain_id`, `block_number`, `status`, `revision`
7. **Retrieve the record from the application** via `GET /api/ledger/transactions/{tx_id}`
8. **Independently query the smart contract** via `web3` — `revisionCounts(recordId)`, `eth_getTransactionReceipt(txHash)`
9. **Compare on-chain digest and record info** against the application's registration — revision counter match, contract address match, chain ID match
10. **Display correct blockchain verification status** — confirmed/failed/not-anchored labels

## Key Assertions

- **No silent fallback:** When `AUTHENTIQ_LEDGER_MODE=polygon` and the RPC is unreachable, `LedgerService.__init__` raises `LedgerUnavailable` instead of falling back to simulation.
- **No duplicate submissions:** Idempotency key on `LedgerTransaction` prevents duplicate on-chain transactions on retry.
- **On-chain verification before confirmation:** A registration is only reported as blockchain-confirmed after `web3.eth.get_transaction_receipt()` confirms `status == 1`.
- **Distinguishable records:** `Registration.ledger_mode` and `LedgerTransaction.mode` clearly distinguish `"simulation"` from `"polygon"`.
- **All required fields persisted:** `tx_id`, `block_number`, `contract_address`, `chain_id`, `status`, `revision`, `chain_tx_hash`, `record_id`, `record_type`, `payload_digest`, `timestamp`.

## Files Changed

| File | Change |
|---|---|
| `backend/app/ledger/blockchain.py` | Rewrote `PolygonAdapter`: chain ID validation, dynamic gas estimation, comprehensive error handling (RPC timeout, insufficient funds, invalid address, unauthorized writer, failed transaction), revision capture via `revisionCounts()`, `is_connected()` exception handling |
| `backend/app/ledger/service.py` | Rewrote `LedgerService`: no silent fallback to simulation, idempotency checks, persists all new fields (`contract_address`, `chain_id`, `revision`, `idempotency_key`), sets `Registration.ledger_mode` from transaction mode |
| `backend/app/models/registration.py` | Added `idempotency_key`, `contract_address`, `chain_id`, `revision` columns to `LedgerTransaction` |
| `backend/app/core/migrations.py` | Added migration entries for the 4 new columns + idempotency index |
| `backend/app/services/serializers.py` | Added `contract_address`, `chain_id`, `revision` to `ledger_out()` |
| `backend/requirements.txt` | Added `web3>=7.0.0`, `eth-account>=0.13.0` |
| `backend/tests/test_blockchain_integration.py` | New: 11 end-to-end integration tests |
| `blockchain/scripts/deploy_local.js` | New: local Hardhat deployment script |
| `blockchain/hardhat.config.js` | Added `localhost` network configuration |

## Running the Tests

```powershell
# From backend directory
.venv\Scripts\python.exe -m pytest tests/test_blockchain_integration.py -v
```

The test suite:
1. Starts a local Hardhat node (`npx hardhat node`)
2. Deploys `AuthentiqRegistry.sol` via `hardhat run scripts/deploy_local.js --network localhost`
3. Configures the FastAPI backend for Polygon mode against the local contract
4. Runs all 11 integration tests
5. Cleans up the Hardhat node process

## Manual Polygon Amoy Deployment

For approved manual testing on Polygon Amoy testnet:

```powershell
# From blockchain directory
cd blockchain
Copy-Item .env.example .env
# Edit .env: set AMOY_RPC_URL, DEPLOYER_PRIVATE_KEY, POLYGONSCAN_API_KEY
# Fund deployer with testnet POL from the Amoy faucet
npm run deploy:amoy
```

The deployment script validates:
- Chain ID is 80002 (not mainnet 137)
- Deployer has non-zero POL balance
- Contract address is valid
- RPC is reachable

## Never

- Deploy to Polygon mainnet (chainId 137) — the script explicitly refuses
- Store original files or private user information on-chain — only identifiers and SHA-256 digests
- Use a mainnet private key for deployment — use a dedicated low-value testnet key
- Silently fall back to simulation when Polygon mode is enabled and a blockchain operation fails
