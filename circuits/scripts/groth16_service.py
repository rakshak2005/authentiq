"""
AUTHENTIQ Groth16 Proof Service (Python wrapper)

Calls the Node.js snarkjs-based proof service for Groth16 proof generation
and verification. The actual zkSNARK operations are performed by snarkjs
against the compiled ownership circuit artifacts.

This module is a SEPARATE proof system from the existing Schnorr sigma
protocol. It does not modify or replace any Schnorr code.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CIRCUITS_DIR = Path(__file__).resolve().parents[2] / "circuits"
GROTH16_JS = CIRCUITS_DIR / "scripts" / "groth16.js"
BUILD_DIR = CIRCUITS_DIR / "build"
NPX = shutil.which("npx") or shutil.which("npx.cmd") or "npx"


class Groth16Error(RuntimeError):
    """Raised when Groth16 proof generation or verification fails."""


@dataclass
class Groth16Proof:
    """A Groth16 proof and its associated public signals."""

    proof: dict[str, Any]
    public_signals: dict[str, Any]


def _run_node(args: list[str], input_text: str | None = None) -> str:
    """Run a node command and return stdout."""
    try:
        result = subprocess.run(
            [NPX, "--no-install", "snarkjs"] + args,
            cwd=CIRCUITS_DIR,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=120,
        )
    except FileNotFoundError:
        raise Groth16Error("node executable not found. Install Node.js to use Groth16 proofs.")
    except subprocess.TimeoutExpired:
        raise Groth16Error("Groth16 operation timed out.")

    if result.returncode != 0:
        raise Groth16Error(f"node command failed: {result.stderr.strip()}")

    return result.stdout.strip()


def _field_to_dec(field_str: str) -> str:
    """
    Convert a field element string to decimal for snarkjs input.

    snarkjs expects decimal strings. This function accepts either:
    - A decimal string (e.g. "12345") - passed through as-is
    - A hex string with "0x" prefix (e.g. "0x1a2b") - converted to decimal
    - A hex string without prefix (e.g. "1a2b") - converted to decimal

    A string is treated as hex only if it contains non-decimal characters
    (a-f, A-F) or starts with "0x". Pure digit strings are assumed decimal.
    """
    s = field_str.strip()
    if s.startswith("0x") or s.startswith("0X"):
        return str(int(s[2:], 16))
    # If the string contains any hex letter, treat it as hex
    if any(c in s for c in "abcdefABCDEF"):
        return str(int(s, 16))
    # Otherwise assume it's already decimal
    return s


def generate_proof(
    fingerprint: str,
    secret: str,
    commitment: str,
) -> Groth16Proof:
    """
    Generate a Groth16 proof of knowledge of the secret opening for a
    Poseidon commitment.

    Statement: commitment = Poseidon(fingerprint, secret)

    Args:
        fingerprint: Decimal field element string (SHA-256 file digest mod p).
                     Hex strings with "0x" prefix are also accepted.
        secret: Decimal scalar string (private witness). Hex strings accepted.
        commitment: Decimal Poseidon commitment value string (public input).
                     Hex strings accepted.

    Returns:
        Groth16Proof with proof and public_signals.

    Raises:
        Groth16Error: If proof generation fails.
    """
    if not GROTH16_JS.exists():
        raise Groth16Error(f"Groth16 service script not found: {GROTH16_JS}")

    # snarkjs expects decimal field element strings
    input_data = {
        "fingerprint": _field_to_dec(fingerprint),
        "secret": _field_to_dec(secret),
        "commitment": _field_to_dec(commitment),
    }
    input_path = BUILD_DIR / "input.json"
    input_path.write_text(json.dumps(input_data))

    proof_path = BUILD_DIR / "proof.json"
    public_path = BUILD_DIR / "public.json"

    # Run snarkjs groth16 fullprove (witness calculation + proof generation)
    wasm_path = BUILD_DIR / "ownership.wasm"
    zkey_path = BUILD_DIR / "ownership_final.zkey"

    for p in [wasm_path, zkey_path]:
        if not p.exists():
            raise Groth16Error(f"Circuit artifact not found: {p}. Compile the circuit first.")

    result = subprocess.run(
        [
            NPX,
            "--no-install",
            "snarkjs",
            "groth16",
            "fullprove",
            str(input_path),
            str(wasm_path),
            str(zkey_path),
            str(proof_path),
            str(public_path),
        ],
        capture_output=True,
        text=True,
        cwd=CIRCUITS_DIR,
        timeout=120,
    )

    if result.returncode != 0:
        output = f"{result.stdout}\n{result.stderr}".strip()
        raise Groth16Error(f"Proof generation failed: {output}")

    if not proof_path.exists() or not public_path.exists():
        raise Groth16Error("Proof generation did not produce output files.")

    proof = json.loads(proof_path.read_text())
    public_signals = json.loads(public_path.read_text())

    return Groth16Proof(proof=proof, public_signals=public_signals)


def verify_proof(
    proof: dict[str, Any],
    public_signals: dict[str, Any],
) -> bool:
    """
    Independently verify a Groth16 proof against the verification key.

    Args:
        proof: The proof object (from generate_proof).
        public_signals: The public signals object (from generate_proof).

    Returns:
        True if the proof is valid, False otherwise.

    Raises:
        Groth16Error: If verification cannot be performed.
    """
    vk_path = BUILD_DIR / "verification_key.json"
    if not vk_path.exists():
        raise Groth16Error(f"Verification key not found: {vk_path}. Run trusted setup first.")

    proof_path = BUILD_DIR / "verify_proof.json"
    public_path = BUILD_DIR / "verify_public.json"
    proof_path.write_text(json.dumps(proof))
    public_path.write_text(json.dumps(public_signals))

    result = subprocess.run(
        [
            NPX,
            "--no-install",
            "snarkjs",
            "groth16",
            "verify",
            str(vk_path),
            str(public_path),
            str(proof_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode == 0 and ("OK!" in output or output == "OK"):
        return True
    if result.returncode != 0 and any(
        marker in output.lower()
        for marker in ("invalid proof", "invalid public input", "assert failed")
    ):
        return False
    raise Groth16Error(f"Proof verification failed unexpectedly: {output}")


def verify_proof_from_files(
    proof_path: str | Path,
    public_path: str | Path,
) -> bool:
    """
    Verify a Groth16 proof from JSON files.

    Args:
        proof_path: Path to proof JSON file.
        public_path: Path to public signals JSON file.

    Returns:
        True if the proof is valid, False otherwise.
    """
    vk_path = BUILD_DIR / "verification_key.json"
    if not vk_path.exists():
        raise Groth16Error(f"Verification key not found: {vk_path}.")

    result = subprocess.run(
        [
            NPX,
            "--no-install",
            "snarkjs",
            "groth16",
            "verify",
            str(vk_path),
            str(public_path),
            str(proof_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode == 0 and ("OK!" in output or output == "OK"):
        return True
    if result.returncode != 0 and any(
        marker in output.lower()
        for marker in ("invalid proof", "invalid public input", "assert failed")
    ):
        return False
    raise Groth16Error(f"Proof verification failed unexpectedly: {output}")
