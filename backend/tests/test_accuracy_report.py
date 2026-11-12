"""Regression guards for the measured detection quality.

These are the fast subset of ``scripts/accuracy_report.py``. If a change to the
fingerprint, similarity, proof, or ledger code lowers detection quality, the
suite fails instead of the regression shipping silently.
"""

import hashlib

from app.fingerprint.sha256 import sha256_bytes
from app.ledger import ledger_service
from app.services.analysis import dhash_bytes, hamming_similarity, text_similarity
from app.zkp.sigma import create_commitment, generate_proof, verify_proof
from scripts.accuracy_report import (
    PERCEPTUAL_THRESHOLD,
    TEXT_THRESHOLD,
    _encode,
    _synthetic_image,
    _variants,
)

from app.core.database import SessionLocal


def test_fingerprint_is_stable_and_bit_sensitive():
    payload = b"authentiq-accuracy-regression"
    digest = sha256_bytes(payload)
    assert digest == sha256_bytes(payload)
    assert len(digest) == 64
    flipped = bytes([payload[0] ^ 0x01]) + payload[1:]
    assert sha256_bytes(flipped) != digest


def test_perceptual_signal_detects_transformations_and_ignores_other_images():
    detected = 0
    total = 0
    for seed in range(6):
        image = _synthetic_image(seed)
        base = dhash_bytes(_encode(image))
        assert base
        for _, data, _same in _variants(image):
            other = dhash_bytes(data)
            total += 1
            if other and hamming_similarity(base, other) >= PERCEPTUAL_THRESHOLD:
                detected += 1
        other_image = dhash_bytes(_encode(_synthetic_image(seed + 5000)))
        assert other_image
        assert hamming_similarity(base, other_image) < PERCEPTUAL_THRESHOLD
    recall = detected / total
    assert recall >= 0.90, f"perceptual recall dropped to {recall}"


def test_text_signal_separates_related_and_unrelated_documents():
    base = "the ownership certificate binds a fingerprint to a commitment and an append only ledger record for later proof"
    variant = "the ownership certificate binds a fingerprint to a commitment and an append only ledger record for later proof"
    unrelated = "invoice for consulting hours rendered in march with the client billing address on the second page"
    assert text_similarity(base, variant) >= TEXT_THRESHOLD
    assert text_similarity(base, unrelated) < TEXT_THRESHOLD


def test_proof_completeness_and_soundness():
    for index in range(5):
        fingerprint = hashlib.sha256(f"accuracy-regression-{index}".encode()).hexdigest()
        registration_id = f"AQ-2026-REG{index:04d}"
        nonce = f"nonce-{index}-abcdefghijklmnop"
        commitment = create_commitment(fingerprint)
        proof = generate_proof(
            fingerprint,
            registration_id,
            nonce,
            commitment["pedersen_commitment"],
            commitment["secret_int"],
            commitment["blinding_int"],
        )
        assert verify_proof(proof, fingerprint, registration_id, nonce, commitment["pedersen_commitment"])[0] is True

        z1 = proof["response"][0]
        tampered = {**proof, "response": [z1[:-1] + ("0" if z1[-1] != "0" else "1"), proof["response"][1]]}
        assert verify_proof(tampered, fingerprint, registration_id, nonce, commitment["pedersen_commitment"])[0] is False

        wrong = create_commitment(fingerprint)
        forged = generate_proof(
            fingerprint,
            registration_id,
            nonce,
            commitment["pedersen_commitment"],
            wrong["secret_int"],
            wrong["blinding_int"],
        )
        assert verify_proof(forged, fingerprint, registration_id, nonce, commitment["pedersen_commitment"])[0] is False

        assert verify_proof(proof, fingerprint, "AQ-2026-OTHER0001", nonce, commitment["pedersen_commitment"])[0] is False
        assert verify_proof(proof, hashlib.sha256(b"other").hexdigest(), registration_id, nonce, commitment["pedersen_commitment"])[0] is False


def test_ledger_detects_edits_and_the_database_cross_check_detects_truncation():
    from app.core.config import settings
    from app.services.integrity import ledger_truncation_check

    with SessionLocal() as db:
        ledger_service._record(db, "accuracy_probe", "actor", "registration", "AQ-2026-PROBE", {"probe": True})
        db.commit()

    path = settings.ledger_file
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    try:
        broken = lines[:-1] + [lines[-1].replace('"accuracy_probe"', '"accuracy_probE"')]
        path.write_text("\n".join(broken) + "\n", encoding="utf-8")
        assert ledger_service.audit()["valid"] is False

        path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        with SessionLocal() as db:
            issues = ledger_truncation_check(db, ledger_service.audit())
        assert issues, "a truncated ledger file must be reported against the database copy"
    finally:
        path.write_text(original, encoding="utf-8")
