# AUTHENTIQ accuracy report

Generated 2026-11-12T10:01:20.520801+00:00 by `python -m scripts.accuracy_report`.

AUTHENTIQ is not a trained model, so it has no single accuracy number. It is a stack of measurable components, and each one is measured here against labelled ground truth with the same code the product runs.

| Component | Headline result |
| --- | --- |
| Exact fingerprint accuracy (SHA-256) | Deterministic digests over distinct payloads: stable, collision free. |
| Perceptual duplicate detection accuracy (dHash-64) | At the shipped threshold 0.9: precision 1.0, recall 0.9722, F1 0.9859 over 384 labelled pairs. |
| Text similarity detection accuracy (4-shingle Jaccard) | At the shipped threshold 0.72: precision 1.0, recall 1.0, F1 1.0 over 120 labelled pairs. |
| Ownership proof accuracy (BN254 Schnorr) | Completeness 1.0 (40/40 valid proofs accepted), soundness 1.0 (320/320 forgeries rejected). |
| Authorization decision accuracy (live API) | 20/20 authorization decisions matched the expected policy (1.0). |
| Ledger and audit tamper detection | Clean chain valid: True. Detection rate for silent edits: 1.0 (32/32). Tail removal seen by the chain alone: False; seen by the database cross-check: True. |

## Exact fingerprint accuracy (SHA-256)

Deterministic digests over distinct payloads: stable, collision free.

**How to read this**

- SHA-256 is not a learned model. It has no accuracy metric in the ML sense; the measurable property is that identical bytes always map to the same digest and distinct bytes never collide in practice.
- Across 400 random payloads the closest pair of digests still differed in 88 of 256 bits.

## Perceptual duplicate detection accuracy (dHash-64)

At the shipped threshold 0.9: precision 1.0, recall 0.9722, F1 0.9859 over 384 labelled pairs.

| Variant | Pairs | Precision | Recall | F1 |
| --- | --- | --- | --- | --- |
| blur radius 1.0 | 24 | 1.0 | 1.0 | 1.0 |
| brightness +15 | 24 | 1.0 | 1.0 | 1.0 |
| brightness -15 | 24 | 1.0 | 1.0 | 1.0 |
| crop 3 percent | 24 | 1.0 | 0.75 | 0.8571 |
| jpeg quality 70 | 24 | 1.0 | 1.0 | 1.0 |
| jpeg quality 90 | 24 | 1.0 | 1.0 | 1.0 |
| lossless re-encode | 24 | 1.0 | 1.0 | 1.0 |
| resized 50% | 24 | 1.0 | 1.0 | 1.0 |
| saved as jpeg then re-read | 24 | 1.0 | 1.0 | 1.0 |

| Threshold | Precision | Recall | F1 | Accuracy |
| --- | --- | --- | --- | --- |
| 0.70 | 0.9643 | 1.0 | 0.9818 | 0.9792 |
| 0.75 | 0.9818 | 1.0 | 0.9908 | 0.9896 |
| 0.80 | 1.0 | 1.0 | 1.0 | 1.0 |
| 0.85 | 1.0 | 0.9907 | 0.9953 | 0.9948 |
| 0.88 | 1.0 | 0.9815 | 0.9907 | 0.9896 |
| 0.90 | 1.0 | 0.9722 | 0.9859 | 0.9844 |
| 0.93 | 1.0 | 0.9259 | 0.9615 | 0.9583 |
| 0.95 | 1.0 | 0.8935 | 0.9438 | 0.9401 |
| 0.97 | 1.0 | 0.7917 | 0.8837 | 0.8828 |
| 1.00 | 1.0 | 0.5509 | 0.7104 | 0.7474 |

**How to read this**

- This is the shipped signal behind 'similar content' alerts. It is an evidence indicator, not a finding of infringement.
- dHash is a 64-bit structural hash: it is robust to re-encoding, resizing, brightness and mild blur, and it is blind to colour, to solid-colour images (a known false-positive family), and to mirroring.
- The sweep shows the precision/recall trade-off at every threshold so the operating point can be defended with data.

## Text similarity detection accuracy (4-shingle Jaccard)

At the shipped threshold 0.72: precision 1.0, recall 1.0, F1 1.0 over 120 labelled pairs.

| Threshold | Precision | Recall | F1 | Accuracy |
| --- | --- | --- | --- | --- |
| 0.30 | 1.0 | 1.0 | 1.0 | 1.0 |
| 0.40 | 1.0 | 1.0 | 1.0 | 1.0 |
| 0.50 | 1.0 | 1.0 | 1.0 | 1.0 |
| 0.60 | 1.0 | 1.0 | 1.0 | 1.0 |
| 0.72 | 1.0 | 1.0 | 1.0 | 1.0 |
| 0.80 | 1.0 | 0.5 | 0.6667 | 0.6667 |
| 0.90 | 1.0 | 0.5 | 0.6667 | 0.6667 |

**How to read this**

- Only applies to text-like assets; images and binaries use the perceptual and exact signals.
- Word-level shingles make the signal robust to whitespace and formatting but sensitive to rewording.

## Ownership proof accuracy (BN254 Schnorr)

Completeness 1.0 (40/40 valid proofs accepted), soundness 1.0 (320/320 forgeries rejected).

| Attack class | Trials | Accepted (must be 0) |
| --- | --- | --- |
| forged anchor point | 40 | 0 |
| forged challenge | 40 | 0 |
| tampered response z1 | 40 | 0 |
| wrong challenge nonce | 40 | 0 |
| wrong commitment | 40 | 0 |
| wrong file fingerprint | 40 | 0 |
| wrong registration id | 40 | 0 |
| wrong secret (forged proof) | 40 | 0 |

**How to read this**

- Completeness: honest proofs always verify. Soundness: forged proofs never verify.
- Soundness here is empirical over the sampled attack classes; the underlying guarantee comes from the discrete-log hardness of BN254 and the Fiat-Shamir binding of the challenge.

## Authorization decision accuracy (live API)

20/20 authorization decisions matched the expected policy (1.0).

| Case | Method | Path | Expected | Actual | Match |
| --- | --- | --- | --- | --- | --- |
| owner reads own record | GET | /api/registrations/AQ-2026-D3CED678 | 200 | 200 | yes |
| organization member reads record | GET | /api/registrations/AQ-2026-D3CED678 | 200 | 200 | yes |
| pending recipient reads record | GET | /api/registrations/AQ-2026-D3CED678 | 200 | 200 | yes |
| outsider is denied record | GET | /api/registrations/AQ-2026-D3CED678 | 403 | 403 | yes |
| anonymous is refused record | GET | /api/registrations/AQ-2026-D3CED678 | 401 | 401 | yes |
| owner downloads original | GET | /api/registrations/AQ-2026-D3CED678/file | 200 | 200 | yes |
| outsider cannot download original | GET | /api/registrations/AQ-2026-D3CED678/file | 403 | 403 | yes |
| owner reveals private key | GET | /api/registrations/AQ-2026-D3CED678/verification-key | 200 | 200 | yes |
| pending recipient cannot reveal private key | GET | /api/registrations/AQ-2026-D3CED678/verification-key | 403 | 403 | yes |
| org member cannot reveal private key | GET | /api/registrations/AQ-2026-D3CED678/verification-key | 403 | 403 | yes |
| owner proposes a transfer | POST | /api/transfers | 201 | 201 | yes |
| pending recipient cannot propose a transfer | POST | /api/transfers | 403 | 403 | yes |
| site admin opens the console | GET | /api/admin/users | 200 | 200 | yes |
| owner is denied the console | GET | /api/admin/users | 403 | 403 | yes |
| anonymous is refused the console | GET | /api/admin/users | 401 | 401 | yes |
| owner reads the dashboard | GET | /api/dashboard/summary | 200 | 200 | yes |
| any account gets its own dashboard | GET | /api/dashboard/summary | 200 | 200 | yes |
| public anonymous challenge is open | POST | /api/public/verify/anonymous/challenge | 200 | 200 | yes |
| public fingerprint existence check is open | POST | /api/public/fingerprints/check | 200 | 200 | yes |
| public records listing is open | GET | /api/public/records | 200 | 200 | yes |

| Case | Method | Path | Expected | Actual | Match |
| --- | --- | --- | --- | --- | --- |
| owner reads own record | GET | `/api/registrations/AQ-2026-D3CED678` | 200 | 200 | yes |
| organization member reads record | GET | `/api/registrations/AQ-2026-D3CED678` | 200 | 200 | yes |
| pending recipient reads record | GET | `/api/registrations/AQ-2026-D3CED678` | 200 | 200 | yes |
| outsider is denied record | GET | `/api/registrations/AQ-2026-D3CED678` | 403 | 403 | yes |
| anonymous is refused record | GET | `/api/registrations/AQ-2026-D3CED678` | 401 | 401 | yes |
| owner downloads original | GET | `/api/registrations/AQ-2026-D3CED678/file` | 200 | 200 | yes |
| outsider cannot download original | GET | `/api/registrations/AQ-2026-D3CED678/file` | 403 | 403 | yes |
| owner reveals private key | GET | `/api/registrations/AQ-2026-D3CED678/verification-key` | 200 | 200 | yes |
| pending recipient cannot reveal private key | GET | `/api/registrations/AQ-2026-D3CED678/verification-key` | 403 | 403 | yes |
| org member cannot reveal private key | GET | `/api/registrations/AQ-2026-D3CED678/verification-key` | 403 | 403 | yes |
| owner proposes a transfer | POST | `/api/transfers` | 201 | 201 | yes |
| pending recipient cannot propose a transfer | POST | `/api/transfers` | 403 | 403 | yes |
| site admin opens the console | GET | `/api/admin/users` | 200 | 200 | yes |
| owner is denied the console | GET | `/api/admin/users` | 403 | 403 | yes |
| anonymous is refused the console | GET | `/api/admin/users` | 401 | 401 | yes |
| owner reads the dashboard | GET | `/api/dashboard/summary` | 200 | 200 | yes |
| any account gets its own dashboard | GET | `/api/dashboard/summary` | 200 | 200 | yes |
| public anonymous challenge is open | POST | `/api/public/verify/anonymous/challenge` | 200 | 200 | yes |
| public fingerprint existence check is open | POST | `/api/public/fingerprints/check` | 200 | 200 | yes |
| public records listing is open | GET | `/api/public/records` | 200 | 200 | yes |

**How to read this**

- Each case is a real HTTP request against the running API, not a unit test of a helper.
- Expected values encode the documented policy: owner, organization member, pending recipient, outsider, anonymous, and site admin.

## Ledger and audit tamper detection

Clean chain valid: True. Detection rate for silent edits: 1.0 (32/32). Tail removal seen by the chain alone: False; seen by the database cross-check: True.

| Tamper class | Trials | Detected |
| --- | --- | --- |
| block number edited | 8 | 8 |
| payload digest edited | 8 | 8 |
| payload edited | 8 | 8 |
| record hash edited | 8 | 8 |

**How to read this**

- Every record carries the hash of its predecessor, so an edit breaks the chain immediately.
- Removing the newest record leaves a structurally valid chain, so the file alone cannot prove it. The shipped mitigation is the independent database copy of every ledger record: the Integrity Center compares the record count and the head hash and reports a truncation.
- The audit log uses the same chaining idea over a separate table.

## How to reproduce

```powershell
cd backend
.\.venv\Scripts\python.exe -m scripts.accuracy_report
```

The harness writes the raw numbers to `storage/accuracy-report.json`. The same corpus generation and thresholds are covered by `backend/tests/test_accuracy_report.py`, so a regression in detection quality fails the test suite instead of silently shipping.

## Honest limits

- Similarity signals are indicators, not legal findings of infringement.
- The perceptual signal is a 64-bit structural hash: robust to re-encoding and resizing, blind to colour and insensitive to mirroring. The measured false-positive families are listed above.
- Proof soundness is empirically sampled per attack class; the formal guarantee comes from the discrete-log assumption of BN254.
- The AI-provenance analyzer is metadata inspection only and reports no classifier score. AUTHENTIQ does not fabricate a detection result when no model is configured.
