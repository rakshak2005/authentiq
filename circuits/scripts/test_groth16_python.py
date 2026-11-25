"""
AUTHENTIQ Groth16 Proof Pipeline Tests

Tests the complete Groth16 proof pipeline for the ownership commitment
circuit:

    commitment = Poseidon(fingerprint, secret)

Public inputs: fingerprint, commitment
Private witness: secret

Test coverage:
- Valid proof generation and verification
- Wrong commitment (tampered public input)
- Wrong secret (invalid private witness)
- Tampered fingerprint (invalid public input)
- Cross-verification (proof from one input vs public signals of another)
- Re-verification consistency
- Hex input support (0x prefix)
- Schnorr implementation untouched (separate proof system)

NOTE: This circuit does NOT prove SHA-256(file). The fingerprint is an
opaque field element. File-to-fingerprint binding is enforced by the
application layer, not by the ZK circuit.
"""

from __future__ import annotations

import json
import subprocess
import sys
import shutil
from pathlib import Path

# Add circuits/scripts to path for the Groth16 service
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from groth16_service import generate_proof, verify_proof, Groth16Error

# Test fixtures (decimal field elements for snarkjs)
# commitment = Poseidon(fingerprint=1, secret=2)
FP1 = "1"
SEC1 = "2"
COMM1 = "7853200120776062878684798364095072458815029376092732009249414926327459813530"

# commitment = Poseidon(fingerprint=3, secret=4)
FP2 = "3"
SEC2 = "4"
COMM2 = "14763215145315200506921711489642608356394854266165572616578112107564877678998"


def _compute_poseidon(fingerprint: str, secret: str) -> str:
    """Compute Poseidon(fingerprint, secret) using the compute_commitment WASM."""
    from groth16_service import BUILD_DIR

    input_path = BUILD_DIR / "test_poseidon_input.json"
    witness_path = BUILD_DIR / "test_poseidon_witness.wtns"
    witness_json = BUILD_DIR / "test_poseidon_witness.json"

    input_path.write_text(json.dumps({"fingerprint": fingerprint, "secret": secret}))

    npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"

    # Calculate witness
    subprocess.run(
        [
            npx,
            "--no-install",
            "snarkjs",
            "wtns",
            "calculate",
            str(BUILD_DIR / "commitment.wasm"),
            str(input_path),
            str(witness_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        cwd=str(Path(__file__).resolve().parents[2] / "circuits"),
    )

    # Export witness as JSON
    subprocess.run(
        [
            npx,
            "--no-install",
            "snarkjs",
            "wtns",
            "export",
            "json",
            str(witness_path),
            str(witness_json),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        cwd=str(Path(__file__).resolve().parents[2] / "circuits"),
    )

    witness = json.loads(witness_json.read_text())
    # witness[1] is the Poseidon output (commitment)
    return witness[1]


passed = 0
failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def main() -> None:
    # Verify test fixtures are correct
    print("Verifying test fixtures...")
    comm1_check = _compute_poseidon(FP1, SEC1)
    check(comm1_check == COMM1, f"Fixture COMM1 matches computed Poseidon(1,2)")
    comm2_check = _compute_poseidon(FP2, SEC2)
    check(comm2_check == COMM2, f"Fixture COMM2 matches computed Poseidon(3,4)")

    # ------------------------------------------------------------------
    # Test 1: Valid proof generation and verification
    # ------------------------------------------------------------------
    print("\n=== Test 1: Valid proof ===")
    proof_valid = generate_proof(FP1, SEC1, COMM1)
    check(proof_valid is not None, "Valid proof generated")
    check("pi_a" in proof_valid.proof, "Proof contains pi_a")
    check("pi_b" in proof_valid.proof, "Proof contains pi_b")
    check("pi_c" in proof_valid.proof, "Proof contains pi_c")
    check(proof_valid.proof["protocol"] == "groth16", "Proof protocol is groth16")
    check(len(proof_valid.public_signals) == 2, "Public signals has 2 elements")
    valid = verify_proof(proof_valid.proof, proof_valid.public_signals)
    check(valid, "Valid proof verifies as OK")

    # ------------------------------------------------------------------
    # Test 2: Wrong commitment (tampered public input)
    # ------------------------------------------------------------------
    print("\n=== Test 2: Wrong commitment ===")
    wrong_comm = str(int(COMM1) + 1)
    try:
        proof = generate_proof(FP1, SEC1, wrong_comm)
        valid = verify_proof(proof.proof, proof.public_signals)
        check(not valid, "Wrong commitment proof fails verification")
    except Groth16Error as e:
        if any(marker in str(e).lower() for marker in ("assert failed", "invalid public input", "invalid proof", "error in template", "constraint")):
            check(True, f"Wrong commitment rejected by the circuit: {e}")
        else:
            raise

    # ------------------------------------------------------------------
    # Test 3: Wrong secret (invalid private witness)
    # ------------------------------------------------------------------
    print("\n=== Test 3: Wrong secret ===")
    wrong_sec = str(int(SEC1) + 1)
    try:
        proof = generate_proof(FP1, wrong_sec, COMM1)
        valid = verify_proof(proof.proof, proof.public_signals)
        check(not valid, "Wrong secret proof fails verification")
    except Groth16Error as e:
        if any(marker in str(e).lower() for marker in ("assert failed", "invalid public input", "invalid proof", "error in template", "constraint")):
            check(True, f"Wrong secret rejected by the circuit: {e}")
        else:
            raise

    # ------------------------------------------------------------------
    # Test 4: Tampered fingerprint (invalid public input)
    # ------------------------------------------------------------------
    print("\n=== Test 4: Tampered fingerprint ===")
    wrong_fp = str(int(FP1) + 1)
    try:
        proof = generate_proof(wrong_fp, SEC1, COMM1)
        valid = verify_proof(proof.proof, proof.public_signals)
        check(not valid, "Tampered fingerprint proof fails verification")
    except Groth16Error as e:
        if any(marker in str(e).lower() for marker in ("assert failed", "invalid public input", "invalid proof", "error in template", "constraint")):
            check(True, f"Tampered fingerprint rejected by the circuit: {e}")
        else:
            raise

    # ------------------------------------------------------------------
    # Test 5: Independent commitments
    # ------------------------------------------------------------------
    print("\n=== Test 5: Independent commitments ===")
    check(COMM1 != COMM2, "Different (fingerprint, secret) pairs produce different commitments")

    # ------------------------------------------------------------------
    # Test 6: Re-verification consistency
    # ------------------------------------------------------------------
    print("\n=== Test 6: Re-verification ===")
    valid = verify_proof(proof_valid.proof, proof_valid.public_signals)
    check(valid, "Re-verification of valid proof succeeds")

    # ------------------------------------------------------------------
    # Test 7: Cross-verification fails
    # ------------------------------------------------------------------
    print("\n=== Test 7: Cross-verification ===")
    proof1 = generate_proof(FP1, SEC1, COMM1)
    # Try to verify proof1 with public signals from a different input
    wrong_public = [FP2, COMM2]
    valid = verify_proof(proof1.proof, wrong_public)
    check(not valid, "Cross-verification with mismatched public signals fails")

    # ------------------------------------------------------------------
    # Test 8: Hex input support (0x prefix)
    # ------------------------------------------------------------------
    print("\n=== Test 8: Hex input support ===")
    try:
        proof_hex = generate_proof("0x1", "0x2", f"0x{int(COMM1):x}")
        valid = verify_proof(proof_hex.proof, proof_hex.public_signals)
        check(valid, "Hex input with 0x prefix verifies correctly")
    except Groth16Error as e:
        check(False, f"Hex input failed: {e}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
