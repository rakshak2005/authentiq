# AUTHENTIQ Development Baseline

Established 2026-11-14. Reproducible verification of the current repository state before any product-directed changes.

## Environment

| Component | Version / location |
|---|---|
| OS | Windows (PowerShell 5.1) |
| Python | 3.13.15 (`backend/.venv`) |
| Node.js | 22.20.0 / npm 11.21.2 |
| Backend deps | `backend/requirements.txt` (all installed; `web3`/`eth-account` NOT installed — polygon is optional) |
| Frontend | `frontend/node_modules` present |
| Blockchain | `blockchain/node_modules` installed during baseline (`npm install`) |
| Circuits | `circuits/node_modules` installed during baseline; **circom compiler binary not available** |

## Commands Executed

### Backend tests
```
cd backend
.venv\Scripts\python.exe -m pytest -q
```

### Frontend production build
```
cd frontend
npm run build   # tsc --noEmit && vite build
```

### Blockchain (Hardhat) tests
```
cd blockchain
npm install
npm test        # hardhat test
```

### Optional Circom circuit build (attempted)
```
cd circuits
npm install
npm run build   # circom ownership.circom --r1cs --wasm --sym -o build
```

## Results

### Backend test suite — PASS
```
88 passed, 0 failed in 64.49s
```
No test failures. Every test file in `backend/tests/` passed against the configured database (Neon PostgreSQL via `AUTHENTIQ_DATABASE_URL`).

### Frontend production build — PASS
```
tsc --noEmit && vite build
✓ built in 11.10s
2072 modules transformed
dist/index.html 1.42 kB
dist/assets/index-CzdOEwYu.css 82.16 kB
dist/assets/index-snm2O0rn.js 821.72 kB (gzip 223.24 kB)
```
Type-check passed; Vite production build succeeded.

### Blockchain Hardhat tests — PASS
```
Compiled 1 Solidity file successfully (evm target: paris).
6 passing (793ms)
```
Tests: deployer as first writer, recordEvent with backend-compatible signature, revision increments for repeated IDs, empty-digest rejection, owner-only `setWriter`, writer-only `recordEvent`.

### Circom circuit — NOT BUILDABLE in this environment
`npm install` succeeded, but `npm run build` failed: `'circom' is not recognized as an internal or external command`. The npm `circom@0.5.46` package does not provide the actual Circom compiler binary. The circuit is documented as not wired into runtime (`circuits/README.md:5`), so this does not block the application.

## Warnings (non-fatal)

### Backend
- `StarletteDeprecationWarning`: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead (`tests/conftest.py`, `fastapi/telemetry/_api.py`).
- `SAWarning`: Can't sort tables for DROP; unresolvable FK dependency cycle between `organizations` and `users` (`conftest.py:49`).
- `StarletteDeprecationWarning`: `HTTP_422_UNPROCESSABLE_ENTITY` deprecated; use `HTTP_422_UNPROCESSABLE_CONTENT`.
- `PytestCacheWarning`: could not create `.pytest_cache` path — access denied (environment/permission, not a code defect).

### Frontend
- Rollup chunk-size warning: `assets/index-snm2O0rn.js` is 821.72 kB (> 500 kB after minification). Suggests dynamic import/code-splitting; not a build error.

### Blockchain
- `npm install` deprecation/vulnerability audit warnings (inflight, glob, lodash.isequal; 45 vulnerabilities). No test impact.

### Circuits
- `npm install` 3 high severity vulnerabilities; build blocked by missing circom compiler binary.

## Build Errors
None. Backend tests, frontend build, and blockchain tests all completed without errors.

## Defects Fixed
**None.** All existing tests pass and all builds succeed, so there are no pre-existing defects that prevent the application from functioning. No business logic, cryptographic algorithms, or API contracts were changed.

## Current Test Coverage

| Area | Test file | Test count |
|---|---|---|
| Registration | `tests/test_registrations.py` | 8 |
| Ledger operations | `tests/test_ledger_audit.py` | 4 |
| Ownership transfers | `tests/test_ownership_transfer.py` | 4 |
| Transfers (general) | `tests/test_transfers.py` | 2 |
| Public verification (anonymous) | `tests/test_anonymous_verification.py` | 7 |
| Public records | `tests/test_public_records.py` | 4 |
| ZKP (Schnorr) | `tests/test_zkp.py` | 5 |
| Integrity center | `tests/test_integrity.py` | 3 |
| Audit chain | `tests/test_audit_chain.py` | 2 |

Registration, ledger operations, ownership transfers, and public verification are all directly exercised by dedicated test suites. The backend suite total is 88 tests across 22 test files.

## Notes
- `backend/.env` contains a real Neon database password and `AUTHENTIQ_SECRET_KEY`. It is not tracked in git (only `.env.example` is), but it is present in the workspace — rotate before any production deploy.
- `web3`/`eth-account` are not installed; Polygon Amoy mode is opt-in and raises `LedgerUnavailable` without them (documented).
- The default ledger mode is `simulation`; no blockchain transaction is created by default.
