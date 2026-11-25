# AUTHENTIQ Groth16 Trusted Setup Documentation

## Overview

This document describes the trusted setup ceremony for the AUTHENTIQ Groth16 proof pipeline,
the security assumptions, and the proving-key integrity model.

## Circuit

**File:** `circuits/ownership.circom`

**Statement:** `commitment = Poseidon(fingerprint, secret)`

| Signal | Type | Public? | Meaning |
|---|---|---|---|
| `fingerprint` | field element | Yes | SHA-256(file) mod p, opaque field element |
| `commitment` | field element | Yes | Poseidon(fingerprint, secret) output |
| `secret` | field element | No | Random blinding scalar (private witness) |

**Constraints:** 244 R1CS constraints, 245 wires.

**Important:** This circuit does NOT prove SHA-256(file) computation. The fingerprint is treated
as an opaque field element. Binding between the file and its fingerprint is enforced by the
application layer (server-side SHA-256 verification), not by the ZK circuit.

## Trusted Setup Ceremony

The Groth16 proving system requires a trusted setup to generate toxic waste parameters that
must be destroyed after key generation. The ceremony consists of these steps:

### Step 1: Powers of Tau (Phase 1)

```
snarkjs powersoftau new bn128 8 build/pot8_0000.ptau
```

- **Curve:** BN128 (same curve as the circuit)
- **Power:** 8 (2^8 = 256 points, sufficient for 244 constraints)
- **Output:** `build/pot8_0000.ptau` - initial powers of tau file
- **Toxic waste:** The random tau value used to generate this file

### Step 2: Powers of Tau Contribution

```
echo "AUTHENTIQ entropy" | snarkjs powersoftau contribute \
  build/pot8_0000.ptau build/pot8_final.ptau --name="AUTHENTIQ dev"
```

- **Purpose:** Adds entropy from a second contributor to the powers of tau
- **Entropy source:** "AUTHENTIQ entropy" string (development ceremony)
- **Output:** `build/pot8_final.ptau`

> In production, multiple independent contributors should each add entropy. No single
> contributor should know the final toxic waste.

### Step 3: Powers of Tau Phase 2 Preparation

```
snarkjs powersoftau prepare phase2 build/pot8_final.ptau build/pot8_final_phase2.ptau
```

- **Purpose:** Converts phase 1 ptau to phase 2 format for Groth16
- **Output:** `build/pot8_final_phase2.ptau`

### Step 4: Groth16 Setup

```
snarkjs groth16 setup build/ownership.r1cs build/pot8_final_phase2.ptau build/ownership_0000.zkey
```

- **Purpose:** Creates the initial proving key from the circuit R1CS and phase 2 ptau
- **Output:** `build/ownership_0000.zkey` - initial zkey (contains toxic waste)

### Step 5: ZKey Contribution (Beacon)

```
echo "AUTHENTIQ zkey entropy" | snarkjs zkey contribute \
  build/ownership_0000.zkey build/ownership_final.zkey --name="AUTHENTIQ"
```

- **Purpose:** Adds another random contribution to the zkey, further randomizing toxic waste
- **Output:** `build/ownership_final.zkey` - final proving key

### Step 6: Export Verification Key

```
snarkjs zkey export verificationkey build/ownership_final.zkey build/verification_key.json
```

- **Purpose:** Extracts the public verification key from the final zkey
- **Output:** `build/verification_key.json` - can be published, contains no toxic waste

## Generated Artifacts

| File | Purpose | Contains Toxic Waste? | Safe to Publish? |
|---|---|---|---|
| `build/ownership.r1cs` | Circuit constraint system | No | Yes |
| `build/ownership.wasm` | Witness calculator | No | Yes |
| `build/ownership.sym` | Symbol table for debugging | No | Yes |
| `build/pot8_0000.ptau` | Initial powers of tau | Yes | No |
| `build/pot8_final.ptau` | Contributed powers of tau | Yes | No |
| `build/pot8_final_phase2.ptau` | Phase 2 prepared ptau | Yes | No |
| `build/ownership_0000.zkey` | Initial proving key | Yes | No |
| `build/ownership_final.zkey` | Final proving key | Yes | No |
| `build/verification_key.json` | Verification key | No | Yes |

## Security Assumptions

### 1. Toxic Waste Destruction

The powers of tau and zkey files contain toxic waste (random values used during setup).
If these values are recovered, an attacker can forge proofs for false statements.

**Requirement:** All intermediate files containing toxic waste (`*.ptau`, `*.zkey`) must be
securely deleted after the verification key is exported. Only `verification_key.json`,
`ownership.wasm`, and `ownership.r1cs` should be retained.

### 2. Multi-Party Computation

This development ceremony used a single contributor for the ptau contribution and zkey
contribution. In production:

- **Minimum 3 independent contributors** should each add entropy to the ptau
- **Minimum 3 independent contributors** should each contribute to the zkey
- Contributors must be physically/operationally independent
- Each contributor must destroy their local toxic waste after contributing

The security of Groth16 relies on the assumption that **at least one contributor
honestly destroyed their toxic waste**. If all contributors collude or are compromised,
the setup is broken and proofs can be forged.

### 3. Proving Key Integrity

The final proving key (`ownership_final.zkey`) must be verified against the original
circuit R1CS and the phase 2 ptau:

```
snarkjs zkey verify build/ownership.r1cs build/pot8_final_phase2.ptau build/ownership_final.zkey
```

This verifies that the zkey was correctly derived from the circuit and ptau without
tampering. The verification key (`verification_key.json`) can also be published for
independent verification.

### 4. Circuit Integrity

The circuit source (`ownership.circom`) must be reviewed and frozen before the trusted
setup. Any change to the circuit requires a new trusted setup ceremony because the
R1CS, WASM, and keys are all circuit-specific.

The compiled artifacts (`ownership.r1cs`, `ownership.wasm`) must match the circuit
source exactly. Hashes should be recorded:

```
sha256sum circuits/ownership.circom circuits/build/ownership.r1cs circuits/build/ownership.wasm
```

## Verification Key Format

The `verification_key.json` contains:

| Field | Type | Description |
|---|---|---|
| `protocol` | string | "groth16" |
| `curve` | string | "bn128" |
| `nPublic` | number | Number of public inputs (2) |
| `vk_alpha_1` | array | Alpha G1 point |
| `vk_beta_2` | array | Beta G2 point |
| `vk_gamma_2` | array | Gamma G2 point |
| `vk_delta_2` | array | Delta G2 point |
| `vk_IC` | array | Input commitment points (one per public input) |

## Production Deployment Checklist

- [ ] Circuit source reviewed and frozen
- [ ] Multi-party trusted setup with 3+ independent contributors
- [ ] Each contributor destroys their toxic waste
- [ ] zkey verified against R1CS and ptau
- [ ] Verification key published and distributed to all verifiers
- [ ] Proving key (`ownership_final.zkey`) stored in secure HSM or equivalent
- [ ] All intermediate toxic waste files (`*.ptau`, `*.zkey`) securely deleted
- [ ] Circuit artifact hashes recorded for integrity verification
- [ ] Groth16 proof service tested end-to-end (valid + invalid proofs)
- [ ] Schnorr implementation preserved unchanged (separate proof system)

## Separation from Schnorr

The Groth16 proof system is completely separate from the existing Schnorr sigma protocol
(`backend/app/zkp/sigma.py`). Key differences:

| Aspect | Schnorr | Groth16 |
|---|---|---|
| Curve | BN254 G1 | BN128 |
| Proof type | Sigma protocol (interactive made non-interactive via Fiat-Shamir) | zkSNARK (non-interactive) |
| Trusted setup | None | Required |
| Proof generation | Server-side (holds encrypted secrets) | Client-side or server-side |
| Verification | Server-side algebraic check | Pairing-based check against VK |
| Status | Operational in production | Development pipeline |

**The Schnorr implementation is NOT modified or replaced.** Both systems coexist until
the Groth16 pipeline passes all tests and is ready for production migration.
