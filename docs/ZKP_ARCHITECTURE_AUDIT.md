# AUTHENTIQ Zero-Knowledge Proof Architecture Audit

**Scope:** `backend/app/zkp/`, `circuits/ownership.circom`, `circuits/README.md`, runtime proof generation/verification, commitment creation, public verification endpoints, ownership registration, Polygon registry interaction.

**Status:** Read-only audit. No cryptographic implementation was modified.

---

## 1. System Overview

AUTHENTIQ uses a **hybrid proof system**:

1. **Default runtime proof (server-side):** A Schnorr sigma protocol over BN254 G1 (Pedersen commitment opening), implemented in `backend/app/zkp/sigma.py`. Proofs are generated **on the server** because the server holds the encrypted secret/blinding values. A browser-side implementation exists in `frontend/src/lib/schnorr.ts` for the anonymous public verifier path, where the user supplies their private verification key directly to the browser.

2. **Optional Circom circuit (`circuits/ownership.circom`):** A Poseidon commitment relation (`commitment = Poseidon(fingerprint mod p, secret)`). Documented as **not used by the running backend**. The backend's default proof is Schnorr, not Groth16. Groth16 config names (`AUTHENTIQ_GROTH16_WASM/ZKEY/VKEY`) are reserved but unused.

---

## 2. The Schnorr Mathematical Statement

The current default proof demonstrates knowledge of the opening of a **Pedersen commitment** on the BN254 G1 curve.

### Parameters

| Symbol | Meaning | Source |
|---|---|---|
| `G` | Pedersen generator | `GENERATOR = (1, 2)` on BN254 |
| `H` | Pedersen second generator | `hash_to_curve("AUTHENTIQ-PEDERSEN-H-V1")` |
| `s` | Poseidon commitment scalar | `s = Poseidon(fingerprint mod p, secret)` |
| `r` | Blinding scalar | Randomly sampled |
| `C` | Pedersen commitment point | `C = s·G + r·H` |
| `fingerprint` | SHA-256 hex of the file | 64-char lowercase hex |
| `secret` | Random scalar, per-registration | Stored encrypted at rest |
| `p` | BN254 scalar field prime | `21888242871839275222246405745257275088548364400416034343698204186575808495617` |

### Relation proven

The prover knows `(s, r)` such that:

```
C = s·G + r·H   where   s = Poseidon(fingerprint mod p, secret)
```

### Fiat-Shamir transcript

```
anchor     = u1·G + u2·H          (u1, u2 random nonces)
challenge  = SHA256("AUTHENTIQ-SCHNORR-BN254-G1-V1 || anchor || C || fingerprint || registration_id || nonce") mod p
z1         = u1 + challenge · s   mod p
z2         = u2 + challenge · r   mod p
proof      = {commitment: C, anchor, challenge, response: [z1, z2], public_signals}
```

### Verification equation

```
z1·G + z2·H  ==?  anchor + challenge · C
```

**Important caveat:** The Schnorr proof does **not** prove anything about SHA-256(file). The fingerprint is an input to the statement; the proof only binds the prover to knowledge of the Pedersen opening `(s, r)`. Equality between the supplied file hash and the registered `sha256` is checked **outside** the proof, by the server (and by the browser in the public verifier path).

---

## 3. Information Classification

### Public (disclosed in proof / on-chain / API responses)

| Item | Where it appears |
|---|---|
| Registration ID (`registration_id`) | Public reference, public signals |
| File SHA-256 fingerprint | Registration record, challenge response, public signals, public registry endpoint |
| Poseidon commitment hash | Registration record, public signals |
| Pedersen commitment point (`C`) | Registration record (`commitment` column), proof transcript |
| Pedersen commitment opening `s` (= Poseidon value) | **Derivable** from the verification key `aqv1_<s_hex>_<r_hex>` issued to the owner |
| Blinding `r` | **Derivable** from the verification key |
| Proof transcript (anchor, challenge, responses) | Stored in `ZkpProof`, returned to verifier |
| Ledger transaction hash / block number | Registration record, ledger table |

### Private (withheld from proof / verifier)

| Item | Protection |
|---|---|
| Original file contents | Never uploaded during verification; never stored on-chain |
| Secret scalar (`secret`) | AES-256-GCM encrypted at rest in `secret_encrypted`; decrypted server-side only for proof generation |
| Blinding scalar (`r`) | AES-256-GCM encrypted at rest in `blinding_encrypted`; decrypted server-side only |
| Private verification key (`aqv1_<s>_<r>`) | Issued once to the owner at registration; never transmitted to server in the public verifier path (used client-side) |

### What the server knows

- The user's identity (session/auth)
- The registration record: fingerprint, Poseidon commitment, Pedersen commitment point, ledger tx_id, mode
- The decrypted `secret` and `blinding` values (server decrypts `secret_encrypted` / `blinding_encrypted` via `secret_for()` to generate proofs on behalf of the owner)
- Whether a proof was generated and whether it verified
- IP address, timestamps, audit trail

### What the browser knows (public anonymous verifier path)

- The user's private verification key `aqv1_<s>_<r>` (typed/pasted by the user; never sent to the server)
- The file's local SHA-256 (computed client-side via `crypto.subtle.digest`)
- The proof transcript (generated client-side via `generateSchnorrProof`)
- The registration reference ID

---

## 4. Commitment Creation

At registration (`backend/app/services/registration_service.py`):

1. `create_commitment(upload.final_sha256)` samples `secret` and `blinding` randomly.
2. `poseidon_value = Poseidon(fingerprint_field(fingerprint), secret)` where `fingerprint_field = int(fingerprint_hex, 16) % p`.
3. `pedersen_point = s·G + r·H` where `s = poseidon_value`, `r = blinding`.
4. `commitment` column = hex of pedersen point; `poseidon_commitment` column = hex of poseidon value.
5. `secret_encrypted = encrypt_text(format(secret_int, "064x"))`; `blinding_encrypted = encrypt_text(format(blinding_int, "064x"))`.
6. Verification key `aqv1_<poseidon_value_hex>_<blinding_hex>` is derived and returned to the owner.

**Binding:** The Pedersen commitment binds `(s, r)`. The Poseidon commitment binds `(fingerprint mod p, secret)`. The server separately stores `sha256` (the raw fingerprint) and checks it against uploads.

---

## 5. How the File Fingerprint Is Checked

### Server-side registration
- Upload chunks are hashed per-chunk; overall browser fingerprint is recomputed server-side from the stored file (`upload.final_sha256`).
- `sha256` column is set from the recomputed digest.

### Proof generation (`POST /zkp/generate`)
- Client sends `file_sha256`.
- Server checks `constant_time_compare(registration.sha256, payload.file_sha256.lower())` **before** generating the proof.
- Mismatch → HTTP 422, no proof generated.

### Anonymous challenge (`POST /public/verify/anonymous/challenge`)
- Client sends `file_sha256`.
- Server checks `constant_time_compare(registration.sha256, payload.file_sha256.lower())`.
- Mismatch → HTTP 422, no challenge issued.

### Public fingerprint check (`POST /public/fingerprints/check`)
- Public existence check: returns whether `sha256` is registered and how many records hold it. No owner/title disclosed.

**Critical point:** The fingerprint equality check is **outside** the ZK proof. The proof does not constrain the fingerprint computation. An attacker who knows `secret` and `blinding` can open the commitment `C` for any fingerprint value they choose; the server-side check is the only binding between the file and the proof statement.

---

## 6. Challenge Freshness and Replay Prevention

| Mechanism | Implementation |
|---|---|
| One-time nonce | `ZkpChallenge.nonce` (32-byte random token), single-use |
| Nonce invalidation | Prior unused challenges for the same `(registration, user, purpose)` are marked `used_at` when a new one is created |
| Used-once enforcement | `challenge.used_at is not None` → HTTP 409 |
| Expiry | `expires_at = now + zkp_challenge_minutes` (default configurable); expired → HTTP 410 |
| Challenge binding | Nonce is included in the Fiat-Shamir challenge transcript and in `public_signals.challenge_nonce` |
| Server-side verification | Verifier recomputes the expected challenge from `(anchor, commitment, fingerprint, registration_id, nonce)` and compares |

**Weakness:** There is no binding between the challenge nonce and a specific proof generation attempt beyond single-use. A valid proof transcript for nonce N can be replayed against the same nonce N only once (server marks it used), but the transcript itself is not bound to a verifier identity or session. In the anonymous path, `user_id` is set to `registration.user_id` (the owner), not the verifier — the verifier is unauthenticated.

---

## 7. Public Verification Endpoints

### `POST /zkp/challenge` (authenticated)
- Requires login + registration ownership
- Returns challenge, nonce, fingerprint, commitment, statement
- Used by the owner's dashboard verification workspace

### `POST /zkp/generate` (authenticated)
- Rate-limited: 40 proofs / 3600s per user
- Requires `file_sha256` match, valid unused challenge
- Server generates proof (holds encrypted secrets)
- Stores `ZkpProof`, marks challenge used, returns proof + public_signals

### `POST /zkp/verify` (authenticated)
- Requires registration access (owner, org member, team participant, or pending recipient)
- Re-verifies proof server-side
- On success: marks registration `verified`, records ledger entry `proof_verified`

### `POST /public/verify/anonymous/challenge` (public)
- Rate-limited per IP: 30 / 3600s
- Requires `file_sha256` match; registration need not belong to caller
- Returns challenge + public record info (fingerprint, commitment, ledger_tx_id, ledger_mode)

### `POST /public/verify/anonymous/verify` (public)
- Rate-limited per IP: 30 / 3600s
- Browser-generated proof (client holds `aqv1_...` key)
- Server verifies; returns checklist (`registration_exists`, `file_fingerprint_matches`, `challenge_valid`, `proof_valid`, `private_key_disclosed: false`, `login_required: false`)

### `POST /public/fingerprints/check` (public)
- Rate-limited per IP: 120 / 3600s
- Returns `registered` boolean + `records` count only

---

## 8. Ownership Registration Flow

1. User uploads file (chunked, per-chunk SHA-256 verified).
2. Server computes overall `sha256`.
3. `create_commitment(sha256)` → random `secret`, `blinding`, Poseidon value, Pedersen point.
4. `Registration` row created with `sha256`, `commitment` (pedersen hex), `poseidon_commitment`, encrypted secret/blinding.
5. Verification key `aqv1_<poseidon>_<blinding>` returned to owner.
6. Ledger entry `creation_registered` written (simulation or Polygon).
7. Owner can later request a challenge and generate/verify a proof.

**Transfer rotation:** On ownership transfer confirmation, `create_commitment(registration.sha256)` rotates secret/blinding; new verification key issued to the new owner.

---

## 9. Polygon Registry Interaction

- `AuthentiqRegistry.sol` `recordEvent(recordId, recordType, payloadDigest, entityId)` stores `payloadDigest = SHA256(payload)` on-chain.
- The ZK proof commitment/fingerprint is **not** submitted to Polygon. The ledger anchors registration metadata (fingerprint, commitment hex, tx_type), not the ZK proof itself.
- `chain_tx_hash`, `contract_address`, `chain_id`, `revision` are captured in `LedgerTransaction` and exposed via `GET /api/ledger/transactions/{tx_id}`.

---

## 10. What Changes Are Needed for Client-Side Groth16 Proving

To replace the Schnorr sigma protocol with client-side Groth16:

1. **Circuit:** Write a Circom circuit that proves knowledge of `(secret, blinding)` such that `C = Poseidon(fingerprint mod p, secret)·G + blinding·H` — **or** simply `commitment = Poseidon(fingerprint mod p, secret)` matching the existing `ownership.circom`. The existing circuit only proves the Poseidon relation, not the Pedersen opening.

2. **Trusted setup:** Run a multi-party ceremony for the circuit; publish `proving_key`, `verification_key`. The reserved env vars `AUTHENTIQ_GROTH16_WASM/ZKEY/VKEY` would point to these artifacts.

3. **Client-side inputs:** The browser needs `fingerprint`, `secret`, `blinding` as witness inputs. Currently the server holds these encrypted. The private verification key `aqv1_<s>_<r>` contains `s` (Poseidon output) and `r` (blinding), but **not** `secret`. To prove the Pedersen opening client-side, the browser would need `secret` too, which means the key format must change or `secret` must be derivable.

4. **Public inputs:** `fingerprint` (public), `commitment` (public output), optionally `registration_id` and `nonce` (for replay binding — these would need to be circuit inputs or hashed into public signals).

5. **Server-side verification:** Replace `verify_proof` with Groth16 verification using the published verification key; verify public inputs match the registration record and nonce.

6. **Fingerprint binding remains external:** Even with Groth16, SHA-256(file) is not computed inside the circuit. The server still checks `file_sha256 == registration.sha256` outside the proof.

---

## 11. Circuit Soundness and Input-Validation Weaknesses

### `circuits/ownership.circom`

```circom
signal input fingerprint;
signal input secret;
signal output commitment;
component hasher = Poseidon(2);
hasher.inputs[0] <== fingerprint;
hasher.inputs[1] <== secret;
commitment <== hasher.out;
component main {public [fingerprint]} = OwnershipCommitment();
```

**Weaknesses:**

1. **No range check on `fingerprint`:** `fingerprint` is a field element modulo `p` (BN254 scalar prime). A 256-bit SHA-256 digest can be larger than `p`; `int(fingerprint_hex, 16) % p` in the backend reduces it, but the circuit itself accepts any field element. Two different SHA-256 digests that are congruent mod `p` produce the same circuit input. This is a negligible collision risk for SHA-256 but is a real input-validation gap.

2. **No output constraint linking `commitment` to registration:** The circuit outputs `commitment`, but nothing in the circuit binds it to a specific registration ID or nonce. Replay of a valid proof for a different registration is possible unless public signals include `registration_id` and `nonce` (they currently do not in the Circom circuit — only `fingerprint` is public).

3. **No fingerprint range enforcement:** The circuit does not verify that `fingerprint` is a valid 256-bit SHA-256 output (i.e., `< 2^256`). Since `p ≈ 2^254`, the field already constrains values to `< p < 2^254`, so any field element is technically a valid 254-bit number. But the backend reduces SHA-256 mod `p`, so a fingerprint ≥ `p` would map to a smaller field element. The circuit cannot distinguish `fingerprint` from `fingerprint mod p`.

4. **Not integrated:** The circuit is not used at runtime. Groth16 keys do not exist. The reserved config names are placeholders only.

### Schnorr implementation (`sigma.py`)

**Strengths:**
- Uses BN254 G1 with proper point validation (`point_from_hex` checks curve membership).
- `hash_to_curve` for `H` is deterministic and labelspaced.
- Challenge includes all public inputs (anchor, commitment, fingerprint, registration_id, nonce) — prevents substitution attacks.
- `verify_proof` checks `proof.commitment == registered commitment` before verifying the equation — prevents commitment swapping.
- Challenge freshness via single-use nonces with expiry.

**Weaknesses:**
- **Proof generated server-side:** The server holds the decrypted `secret` and `blinding`. The owner does not generate the proof themselves in the authenticated flow (`/zkp/generate`). This means the server learns the opening, which is acceptable for an owner-proving-to-server model but contradicts a "client-only proving" model. The anonymous public path (`PublicAnonymousVerifyPage`) does prove client-side, but requires the user to paste their `aqv1_...` key.
- **`secret` and `blinding` are not bound to fingerprint inside the proof:** The proof shows knowledge of `(s, r)` opening `C`, where `s = Poseidon(fingerprint, secret)`. It does not prove that `fingerprint == SHA256(file)`. That check is server-side only.
- **No proof-of-possession of the private key at registration:** The verification key is issued to the owner, but there's no cryptographic attestation that the recipient actually knows `secret`/`blinding` at issuance time. (This is a design choice, not a bug.)
- **Challenge expiry window** (`zkp_challenge_minutes`) is configurable; no minimum enforcement visible in config.

---

## 12. Summary Table

| Question | Answer |
|---|---|
| What is proven? | Knowledge of Pedersen commitment opening `(s, r)` where `s = Poseidon(fingerprint mod p, secret)` |
| What is public? | Registration ID, fingerprint, commitments, proof transcript, ledger info |
| What is private? | File contents, `secret`, `blinding`, verification key (in anonymous path) |
| What does the server know? | Everything except the browser-computed local hash and (in anonymous path) the user's `aqv1_...` key |
| What does the browser know? | Local file hash, verification key (anonymous path), proof transcript |
| Bound to commitment? | Yes — `proof.commitment` must equal `registration.commitment` |
| Fingerprint checked how? | Server-side `constant_time_compare` before challenge/proof; outside the ZK proof |
| Proof constrains fingerprint? | **No.** The proof does not constrain SHA-256(file) computation |
| Challenge freshness? | Single-use nonce + expiry + transcript binding |
| Groth16 changes needed? | Circuit for Pedersen/Poseidon relation, trusted setup, client witness inputs (secret + blinding), server verification key, public inputs for registration_id/nonce |
| Circuit weaknesses? | No range check on fingerprint, no registration/nonce binding in circuit outputs, not integrated at runtime |

**Bottom line:** The Schnorr implementation is cryptographically sound for what it claims (Pedersen commitment opening), but it does **not** prove SHA-256(file) inside the circuit, and the fingerprint-to-proof binding is enforced by server-side application logic, not by the proof itself.
