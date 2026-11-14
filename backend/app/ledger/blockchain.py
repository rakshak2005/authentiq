from datetime import datetime, timezone

import httpx
from web3.exceptions import (
    ContractLogicError,
    InvalidAddress,
    TimeExhausted,
    Web3Exception,
)

try:
    from web3 import Web3
except ImportError:
    Web3 = None  # type: ignore[assignment]

from app.core.config import settings
from app.ledger.simulation import LedgerAdapter, LedgerUnavailable


class PolygonAdapter(LedgerAdapter):
    mode = "polygon"
    network = "Polygon Amoy"

    CONTRACT_ABI = [
        {
            "inputs": [
                {"internalType": "string", "name": "recordId", "type": "string"},
                {"internalType": "string", "name": "recordType", "type": "string"},
                {"internalType": "string", "name": "payloadDigest", "type": "string"},
                {"internalType": "string", "name": "entityId", "type": "string"},
            ],
            "name": "recordEvent",
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [{"internalType": "string", "name": "recordId", "type": "string"}],
            "name": "revisionCounts",
            "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
    ]

    def __init__(self):
        missing = [
            name
            for name, value in {
                "CHAIN_RPC_URL": settings.chain_rpc_url,
                "CHAIN_PRIVATE_KEY": settings.chain_private_key,
                "CHAIN_CONTRACT_ADDRESS": settings.chain_contract_address,
            }.items()
            if not value
        ]
        if missing:
            raise LedgerUnavailable(
                "Polygon adapter is not configured. Missing: " + ", ".join(missing)
            )

        if Web3 is None:
            raise LedgerUnavailable(
                "Polygon mode requires the optional packages web3 and eth-account. Install them to enable it."
            )

        self._web3 = Web3(Web3.HTTPProvider(settings.chain_rpc_url))
        if not self._web3.is_connected():
            raise LedgerUnavailable("Could not connect to the configured Polygon RPC endpoint")

        self._account = Account.from_key(settings.chain_private_key)

        try:
            self._contract_address = self._web3.to_checksum_address(
                settings.chain_contract_address
            )
        except InvalidAddress as exc:
            raise LedgerUnavailable(f"Invalid contract address: {settings.chain_contract_address}") from exc

        self._contract = self._web3.eth.contract(
            address=self._contract_address,
            abi=self.CONTRACT_ABI,
        )

        self._validate_chain_id()

    def _validate_chain_id(self):
        """Validate the connected chain ID matches the configured chain ID."""
        try:
            connected_chain_id = int(self._web3.eth.chain_id)
        except Exception as exc:
            raise LedgerUnavailable(f"Failed to read chain ID from RPC: {exc}") from exc

        if connected_chain_id != settings.chain_id:
            raise LedgerUnavailable(
                f"Connected chain ID {connected_chain_id} does not match configured chain ID {settings.chain_id}. "
                "Refusing to submit transactions to an unexpected network."
            )

    def _rpc(self, method: str, params: list) -> dict:
        try:
            response = httpx.post(
                settings.chain_rpc_url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=20.0,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LedgerUnavailable(f"RPC request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LedgerUnavailable(f"RPC request failed: {exc}") from exc

        payload = response.json()
        if "error" in payload:
            raise LedgerUnavailable(payload["error"].get("message", "RPC error"))
        return payload.get("result")

    def append(
        self,
        tx_type: str,
        actor_id: str | None,
        entity_type: str,
        entity_id: str,
        payload: dict,
    ) -> dict:
        from app.ledger.simulation import digest

        record_id = entity_id
        payload_digest = digest(payload)

        # Build and sign the transaction
        try:
            nonce = self._web3.eth.get_transaction_count(self._account.address)
        except Exception as exc:
            raise LedgerUnavailable(f"Failed to retrieve transaction nonce: {exc}") from exc

        try:
            tx = self._contract.functions.recordEvent(
                record_id, tx_type, payload_digest, entity_id
            ).build_transaction(
                {
                    "from": self._account.address,
                    "nonce": nonce,
                    "chainId": settings.chain_id,
                    "gas": 300000,
                    "maxFeePerGas": self._web3.to_wei("35", "gwei"),
                    "maxPriorityFeePerGas": self._web3.to_wei("30", "gwei"),
                }
            )
        except ContractLogicError as exc:
            raise LedgerUnavailable(f"Contract rejected transaction: {exc}") from exc
        except InvalidAddress as exc:
            raise LedgerUnavailable(f"Invalid address in transaction: {exc}") from exc
        except Web3Exception as exc:
            raise LedgerUnavailable(f"Failed to build transaction: {exc}") from exc

        try:
            signed = self._account.sign_transaction(tx)
        except Exception as exc:
            raise LedgerUnavailable(f"Failed to sign transaction: {exc}") from exc

        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
        if raw is None:
            raise LedgerUnavailable("Signed transaction has no raw transaction data")

        try:
            tx_hash = self._web3.eth.send_raw_transaction(raw)
        except ContractLogicError as exc:
            raise LedgerUnavailable(f"Contract rejected transaction on submission: {exc}") from exc
        except ValueError as exc:
            # web3 raises ValueError for insufficient funds, nonce issues, etc.
            error_msg = str(exc).lower()
            if "insufficient funds" in error_msg:
                raise LedgerUnavailable("Insufficient funds for deployment transaction") from exc
            if "nonce" in error_msg:
                raise LedgerUnavailable(f"Transaction nonce error: {exc}") from exc
            raise LedgerUnavailable(f"Failed to send transaction: {exc}") from exc
        except TimeExhausted as exc:
            raise LedgerUnavailable(f"Transaction submission timed out: {exc}") from exc
        except Web3Exception as exc:
            raise LedgerUnavailable(f"Failed to send transaction: {exc}") from exc

        tx_hash_hex = self._web3.to_hex(tx_hash)

        # Wait for confirmation with timeout handling
        try:
            receipt = self._web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        except TimeExhausted as exc:
            raise LedgerUnavailable(
                f"Transaction {tx_hash_hex} not confirmed within timeout. It may still be pending."
            ) from exc
        except Web3Exception as exc:
            raise LedgerUnavailable(f"Failed to wait for transaction receipt: {exc}") from exc

        if receipt.status != 1:
            raise LedgerUnavailable(f"Polygon transaction reverted (tx: {tx_hash_hex})")

        # Capture the event revision from the contract state
        try:
            revision = int(self._contract.functions.revisionCounts(record_id).call())
        except Exception as exc:
            # If we can't read the revision, still return the transaction but mark revision as None
            revision = None

        return {
            "tx_id": tx_hash_hex,
            "block_number": receipt.blockNumber,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tx_type": tx_type,
            "actor_id": actor_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": payload,
            "payload_digest": payload_digest,
            "mode": "polygon",
            "network": self.network,
            "status": "confirmed",
            "chain_tx_hash": tx_hash_hex,
            "contract_address": self._contract_address,
            "chain_id": settings.chain_id,
            "revision": revision,
        }

    def verify_chain(self) -> dict:
        try:
            block = int(self._rpc("eth_blockNumber", []), 16)
            chain_id = int(self._rpc("eth_chainId", []), 16)
            return {
                "valid": chain_id == settings.chain_id,
                "records": None,
                "blocks": block,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "errors": [] if chain_id == settings.chain_id else [f"Connected chain id {chain_id} does not match configured chain id {settings.chain_id}"],
                "mode": self.mode,
                "network": self.network,
            }
        except Exception as exc:
            return {
                "valid": False,
                "records": None,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "errors": [str(exc)],
                "mode": self.mode,
                "network": self.network,
            }

    def transactions(self) -> list[dict]:
        return []

    def get_transaction(self, tx_id: str) -> dict | None:
        try:
            receipt = self._rpc("eth_getTransactionReceipt", [tx_id])
        except LedgerUnavailable:
            return None
        if not receipt:
            return None
        return {
            "tx_id": tx_id,
            "status": "confirmed" if int(receipt.get("status", "0x0"), 16) == 1 else "failed",
            "block_number": int(receipt.get("blockNumber", "0x0"), 16),
            "mode": self.mode,
            "network": self.network,
            "chain_tx_hash": tx_id,
            "contract_address": self._contract_address,
            "chain_id": settings.chain_id,
        }

    def status(self) -> dict:
        try:
            chain_id = int(self._rpc("eth_chainId", []), 16)
            block = int(self._rpc("eth_blockNumber", []), 16)
            return {
                "mode": "polygon",
                "label": "Polygon Amoy Connected",
                "connected": True,
                "network": self.network,
                "chain_id": chain_id,
                "contract_address": self._contract_address,
                "block_number": block,
                "tamper_detected": False,
                "errors": [] if chain_id == settings.chain_id else ["Chain id mismatch"],
                "message": "Connected to Polygon Amoy. Records are submitted as real testnet transactions.",
            }
        except Exception as exc:
            return {
                "mode": "polygon",
                "label": "Disconnected",
                "connected": False,
                "network": self.network,
                "chain_id": settings.chain_id,
                "contract_address": settings.chain_contract_address or None,
                "tamper_detected": None,
                "errors": [str(exc)],
                "message": "Polygon Amoy is configured but unreachable.",
            }
