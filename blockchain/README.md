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

## Deploy locally (dry run)

Before deploying to Amoy, validate the deployment script against the local Hardhat network. This does not use real funds or a real private key:

```powershell
cd blockchain
npm install
npx hardhat node   # in one terminal, leaves a local node running
# in another terminal:
npx hardhat run scripts/deploy.js --network hardhat
```

The script will deploy to the local Hardhat network (chainId 31337) and write `deployments/31337.json`. This verifies compilation, deployment logic, and artifact writing without touching Amoy.

## Deploy to Polygon Amoy

### Prerequisites

1. Install dependencies:
   ```powershell
   cd blockchain
   npm install
   ```

2. Create `blockchain/.env` from `blockchain/.env.example`:
   ```powershell
   Copy-Item .env.example .env
   ```
   Fill in `AMOY_RPC_URL` and `DEPLOYER_PRIVATE_KEY`. `POLYGONSCAN_API_KEY` is optional.

3. Fund the deployer address with testnet POL from the Polygon Amoy faucet. The deployer needs sufficient POL to pay gas for contract deployment.

### Deploy

```powershell
cd blockchain
npm run deploy:amoy
```

The deployment script performs the following checks before deploying:

1. **Network validation** — Aborts if connected to Polygon mainnet (chainId 137). Only Amoy (chainId 80002) or local Hardhat are permitted.
2. **Deployer account** — Verifies `DEPLOYER_PRIVATE_KEY` is configured and derives the deployer address.
3. **Balance check** — Verifies the deployer has a non-zero POL balance; warns if below 0.001 POL.
4. **Contract deployment** — Deploys `AuthentiqRegistry`.
5. **Confirmation** — Waits for the deployment transaction receipt and verifies `status == 1`.
6. **Artifact** — Writes `deployments/80002.json` with the contract address, chain ID, deployer, transaction hash, block number, network, and timestamp.

### Deployment artifact

The artifact convention is preserved:

```text
blockchain/deployments/80002.json
```

Example:

```json
{
  "contract": "AuthentiqRegistry",
  "address": "0x...",
  "chainId": 80002,
  "deployer": "0x...",
  "transactionHash": "0x...",
  "blockNumber": 12345678,
  "network": "amoy",
  "deployedAt": "2026-11-14T..."
}
```

## Deployment verification

After deployment, verify the contract on-chain:

1. **Confirm the artifact exists** — `blockchain/deployments/80002.json` contains the deployed address and transaction hash.
2. **Verify on Amoy block explorer** — Open `https://amoy.polygonscan.com/tx/<transactionHash>` and confirm the transaction succeeded.
3. **Check the contract address** — Open `https://amoy.polygonscan.com/address/<address>` and confirm the contract was created.
4. **Read the latest record** — Call `getRecord` with any known `recordId`; it should return a zeroed `Record` until an event is recorded.
5. **Connect the backend** — Set `AUTHENTIQ_CHAIN_CONTRACT_ADDRESS` to the deployed address and `AUTHENTIQ_LEDGER_MODE=polygon` in the backend `.env`. `GET /api/ledger/status` should report `mode: polygon`, `connected: true`, and the configured contract address.

## Manual deployment checklist

```
[ ] 1. Install blockchain dependencies:  cd blockchain && npm install
[ ] 2. Copy .env.example to .env:        Copy-Item .env.example .env
[ ] 3. Fill in AMOY_RPC_URL in .env
[ ] 4. Fill in DEPLOYER_PRIVATE_KEY in .env (dedicated low-value Amoy key only)
[ ] 5. Fund deployer address with testnet POL from the Amoy faucet
[ ] 6. Verify deployer balance > 0 POL
[ ] 7. Run dry run on local Hardhat:     npx hardhat run scripts/deploy.js --network hardhat
[ ] 8. Confirm dry run writes deployments/31337.json
[ ] 9. Run deployment to Amoy:           npm run deploy:amoy
[ ]10. Confirm script aborts if accidentally pointed at mainnet (chainId 137)
[ ]11. Confirm deployments/80002.json is written with address, chainId, deployer, tx hash, block number, timestamp
[ ]12. Verify transaction on Amoy explorer: https://amoy.polygonscan.com/tx/<transactionHash>
[ ]13. Verify contract on Amoy explorer:   https://amoy.polygonscan.com/address/<address>
[ ]14. Call getRecord on the deployed contract to confirm it responds
[ ]15. Set AUTHENTIQ_CHAIN_CONTRACT_ADDRESS in backend .env
[ ]16. Set AUTHENTIQ_LEDGER_MODE=polygon in backend .env
[ ]17. Restart backend and confirm GET /api/ledger/status reports polygon mode
```

## Security notes

- Never commit a private key. Use a dedicated low-value writer key and a secret manager in production. `blockchain/.env` is gitignored.
- The Amoy network is a public testnet. Transactions are real testnet transactions, not a production settlement guarantee.
- The contract stores identifiers and SHA-256 payload digests, not file contents. Do not put confidential material in `recordId`, `recordType`, `payloadDigest`, or `entityId`.
- The contract owner can change writers and transfer ownership. For production, move ownership to a multisig or governed address.
- The registry intentionally does not attempt to interpret or verify AUTHENTIQ's ZK proofs on-chain. Proof verification remains an application-layer operation in this release.
- This script will refuse to deploy to Polygon mainnet (chainId 137).
