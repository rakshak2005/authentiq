# AUTHENTIQ Polygon registry

`AuthentiqRegistry` is the optional Solidity registry used when `AUTHENTIQ_LEDGER_MODE=polygon`. The default AUTHENTIQ setup uses the local append-only simulation ledger and does not deploy or transact on a public chain.

## Contract interface

The backend calls this exact function through `backend/app/ledger/blockchain.py`:

```solidity
function recordEvent(
    string calldata recordId,
    string calldata recordType,
    string calldata payloadDigest,
    string calldata entityId
) external;
```

The contract emits `RecordEvent`, stores the latest record per `recordId`, and increments `revisionCounts[recordId]`. Repeated identifiers are intentional because a registration can produce many events such as creation, versions, provenance, transfer, and dispute records.

Writes are restricted to addresses marked as writers. The deployer becomes the first writer. The backend signing key therefore must be the deployer or be authorized with `setWriter`.

## Contract changes (development baseline)

The following backward-compatible improvements were made to `AuthentiqRegistry.sol` before the first Polygon Amoy deployment. Existing `recordEvent` callers are unaffected.

### New errors
- `InvalidPayloadDigest()` — reverted when `payloadDigest` is not exactly 64 hexadecimal characters (`[0-9a-fA-F]`).
- `InvalidRecordId()` — reverted when `recordId` is an empty string.
- `InvalidNewOwner()` — reverted when `transferOwnership` is called with `address(0)`.

### Digest validation
`recordEvent` now rejects invalid payload digests in addition to empty ones:
- Empty string → `InvalidPayloadDigest` (replaces the previous `EmptyPayloadDigest` for the empty case; `EmptyPayloadDigest` is still emitted explicitly).
- Length other than 64 characters → `InvalidPayloadDigest`.
- Any character outside `[0-9a-fA-F]` → `InvalidPayloadDigest`.

The backend always supplies a 64-character lowercase SHA-256 hex digest, so this change is transparent to existing integrations.

### Record identifier validation
`recordEvent` now rejects an empty `recordId` (`InvalidRecordId`). All backend-supplied record identifiers are non-empty.

### Record revision inspectability
A new mapping `recordRevisions[recordId][revision]` stores every historical record, and a new view function exposes it:

```solidity
function getRecordRevision(string calldata recordId, uint256 revision)
    external
    view
    returns (Record memory)
```

- `getRecord(recordId)` continues to return the latest record unchanged.
- `getRecordRevision(recordId, revision)` returns the record stored at a specific revision number (1-based). Revisions that were never recorded return a zeroed `Record`.
- `revisionCounts[recordId]` returns the latest revision number.

### Ownership administration
- `transferOwnership(newOwner)` now reverts with `InvalidNewOwner` if `newOwner` is `address(0)`, preventing accidental permanent lockout.
- `transferOwnership` now emits an `OwnershipTransferred(previousOwner, newOwner)` event for auditability.
- `setWriter` behavior is unchanged (owner-only, emits `WriterChanged`).

### Event emission
- New event `OwnershipTransferred(address indexed previousOwner, address indexed newOwner)` emitted by `transferOwnership`.
- `RecordEvent` and `WriterChanged` are unchanged.

### Security notes
- Never commit a private key. Use a dedicated low-value writer key and a secret manager in production.
- The Amoy network is a public testnet. Transactions are real testnet transactions, not a production settlement guarantee.
- The contract stores identifiers and SHA-256 payload digests, not file contents. Do not put confidential material in `recordId`, `recordType`, `payloadDigest`, or `entityId`.
- The contract owner can change writers and transfer ownership. For production, move ownership to a multisig or governed address.
- The registry intentionally does not attempt to interpret or verify AUTHENTIQ's ZK proofs on-chain. Proof verification remains an application-layer operation in this release.

## Install and test

```powershell
cd blockchain
npm install
npm test
```

The test suite uses the Hardhat in-process network. It covers deployment, authorization, event recording, revision counters, empty-digest rejection, and writer enforcement.

## Deploy to Polygon Amoy

Create `blockchain/.env`:

```text
DEPLOYER_PRIVATE_KEY=0x...
AMOY_RPC_URL=https://rpc-amoy.polygon.technology
POLYGONSCAN_API_KEY=
```

Fund the deployer with testnet POL from the Polygon Amoy faucet. Then run:

```powershell
cd blockchain
npm run deploy:amoy
```

The script prints and writes `deployments/80002.json` with the contract address, chain ID, deployer, and deployment timestamp.

## Connect the backend

Set these values in the root `.env` or `backend/.env`:

```text
AUTHENTIQ_LEDGER_MODE=polygon
AUTHENTIQ_CHAIN_RPC_URL=https://rpc-amoy.polygon.technology
AUTHENTIQ_CHAIN_PRIVATE_KEY=0x...
AUTHENTIQ_CHAIN_CONTRACT_ADDRESS=0x...
AUTHENTIQ_CHAIN_ID=80002
AUTHENTIQ_CHAIN_EXPLORER_URL=https://amoy.polygonscan.com
```

Install the optional Python packages before starting the backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install "web3>=7" "eth-account>=0.13"
```

Restart the API. `GET /api/ledger/status` should report `mode: polygon`, `connected: true`, and the configured contract address. If configuration is missing or the RPC is unreachable, ledger-backed operations fail clearly instead of silently falling back to simulation.

## Security notes

- Never commit a private key. Use a dedicated low-value writer key and a secret manager in production.
- The Amoy network is a public testnet. Transactions are real testnet transactions, not a production settlement guarantee.
- The contract stores identifiers and SHA-256 payload digests, not file contents. Do not put confidential material in `recordId`, `recordType`, `payloadDigest`, or `entityId`.
- The contract owner can change writers. For production, move ownership to a multisig or governed address.
- The registry intentionally does not attempt to interpret or verify AUTHENTIQ's ZK proofs on-chain. Proof verification remains an application-layer operation in this release.
