"""AUTHENTIQ accuracy harness.

Measures how accurate the shipped detection, proof, and authorization layers
actually are, using the real implementations (not re-implementations):

* exact fingerprint accuracy (SHA-256)
* perceptual duplicate detection accuracy (dHash-64, shipped threshold 0.90)
* text similarity detection accuracy (4-shingle Jaccard, shipped threshold 0.72)
* zero-knowledge proof soundness and completeness (BN254 Schnorr)
* authorization decision accuracy (live API, role x resource matrix)
* ledger tamper detection rate

Run it with:

    python -m scripts.accuracy_report

It writes ``storage/accuracy-report.json`` and ``docs/ACCURACY.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import secrets
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = Path(tempfile.mkdtemp(prefix="authentiq-accuracy-"))

os.environ["AUTHENTIQ_ENVIRONMENT"] = "test"
os.environ["AUTHENTIQ_DEBUG"] = "false"
os.environ["AUTHENTIQ_SEED_DEMO"] = "false"
os.environ["AUTHENTIQ_SECRET_KEY"] = "authentiq-accuracy-secret-key-0123456789"
os.environ["AUTHENTIQ_DATABASE_URL"] = f"sqlite:///{(WORK_ROOT / 'accuracy.db').as_posix()}"
os.environ["AUTHENTIQ_STORAGE_DIR"] = str(WORK_ROOT / "storage")
os.environ["AUTHENTIQ_UPLOAD_DIR"] = str(WORK_ROOT / "storage" / "uploads")
os.environ["AUTHENTIQ_EVIDENCE_DIR"] = str(WORK_ROOT / "storage" / "evidence")
os.environ["AUTHENTIQ_LEDGER_FILE"] = str(WORK_ROOT / "storage" / "ledger.jsonl")
os.environ["AUTHENTIQ_LEDGER_MODE"] = "simulation"
os.environ["AUTHENTIQ_LOGIN_RATE_LIMIT"] = "100000"
os.environ["AUTHENTIQ_REGISTRATION_RATE_LIMIT"] = "100000"

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from app.fingerprint.sha256 import sha256_bytes  # noqa: E402
from app.services.analysis import dhash_bytes, hamming_similarity, text_similarity  # noqa: E402
from app.zkp.sigma import create_commitment, generate_proof, verify_proof  # noqa: E402

PERCEPTUAL_THRESHOLD = 0.90
TEXT_THRESHOLD = 0.72


# --------------------------------------------------------------------------
# metric helpers
# --------------------------------------------------------------------------


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, predicted_positive: bool, actual_positive: bool) -> None:
        if predicted_positive and actual_positive:
            self.tp += 1
        elif predicted_positive and not actual_positive:
            self.fp += 1
        elif not predicted_positive and actual_positive:
            self.fn += 1
        else:
            self.tn += 1

    @property
    def precision(self) -> float:
        denominator = self.tp + self.fp
        return round(self.tp / denominator, 4) if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.tp + self.fn
        return round(self.tp / denominator, 4) if denominator else 0.0

    @property
    def f1(self) -> float:
        return round(2 * self.precision * self.recall / (self.precision + self.recall), 4) if (self.precision + self.recall) else 0.0

    @property
    def accuracy(self) -> float:
        total = self.tp + self.fp + self.fn + self.tn
        return round((self.tp + self.tn) / total, 4) if total else 0.0

    def as_dict(self) -> dict:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "accuracy": self.accuracy,
            "pairs": self.tp + self.fp + self.fn + self.tn,
        }


@dataclass
class Section:
    name: str
    title: str
    summary: str
    metrics: dict = field(default_factory=dict)
    tables: list = field(default_factory=list)
    notes: list = field(default_factory=list)


# --------------------------------------------------------------------------
# 1. exact fingerprint accuracy
# --------------------------------------------------------------------------


def measure_fingerprint_accuracy(samples: int = 400) -> Section:
    digests: dict[str, str] = {}
    for index in range(samples):
        payload = f"authentiq-accuracy-sample-{index}-{secrets.token_hex(16)}".encode()
        digests[payload.hex()] = sha256_bytes(payload)

    stable = all(
        sha256_bytes(bytes.fromhex(payload)) == digest for payload, digest in digests.items()
    )
    unique = len(set(digests.values())) == len(digests)

    # one-bit sensitivity
    base = b"bit-flip-sensitivity-probe"
    base_digest = sha256_bytes(base)
    flipped = bytes([base[0] ^ 0x01]) + base[1:]
    bit_flip_detected = sha256_bytes(flipped) != base_digest

    # empirical minimum Hamming distance between distinct digests
    values = list(digests.values())
    minimum_distance = 256
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            distance = (int(values[i], 16) ^ int(values[j], 16)).bit_count()
            minimum_distance = min(minimum_distance, distance)
            if minimum_distance == 0:
                break

    confusion = Confusion()
    for payload, digest in digests.items():
        confusion.add(predicted_positive=digest == base_digest, actual_positive=payload == base.hex())

    return Section(
        name="fingerprint",
        title="Exact fingerprint accuracy (SHA-256)",
        summary=(
            "Deterministic digests over distinct payloads: "
            f"{'stable' if stable else 'UNSTABLE'}, {'collision free' if unique else 'COLLISION DETECTED'}."
        ),
        metrics={
            "samples": samples,
            "digest_stability": stable,
            "collision_free": unique,
            "single_bit_change_detected": bit_flip_detected,
            "minimum_observed_hamming_distance_bits": minimum_distance,
            "pair_classification": confusion.as_dict(),
        },
        notes=[
            "SHA-256 is not a learned model. It has no accuracy metric in the ML sense; "
            "the measurable property is that identical bytes always map to the same digest "
            "and distinct bytes never collide in practice.",
            f"Across {samples} random payloads the closest pair of digests still differed in "
            f"{minimum_distance} of 256 bits.",
        ],
    )


# --------------------------------------------------------------------------
# 2 + 3. duplicate detection corpus
# --------------------------------------------------------------------------


def _synthetic_image(seed: int, size: int = 320) -> Image.Image:
    rng = random.Random(seed)
    image = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(image)
    for _ in range(rng.randint(14, 26)):
        x0 = rng.randint(0, size - 20)
        y0 = rng.randint(0, size - 20)
        x1 = x0 + rng.randint(18, 110)
        y1 = y0 + rng.randint(18, 110)
        value = rng.randint(20, 235)
        if rng.random() < 0.45:
            draw.ellipse([x0, y0, x1, y1], fill=value)
        else:
            draw.rectangle([x0, y0, x1, y1], fill=value)
    for _ in range(rng.randint(6, 12)):
        y = rng.randint(0, size - 1)
        draw.line([0, y, size, rng.randint(0, size - 1)], fill=rng.randint(0, 255), width=rng.randint(1, 3))
    return image.filter(ImageFilter.GaussianBlur(radius=0.6))


def _encode(image: Image.Image, fmt: str = "PNG", **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def _variants(image: Image.Image) -> list[tuple[str, bytes, bool]]:
    """(label, encoded bytes, is_same_creation)."""
    width, height = image.size
    variants: list[tuple[str, bytes, bool]] = [
        ("lossless re-encode", _encode(image), True),
        ("jpeg quality 90", _encode(image.convert("RGB"), "JPEG", quality=90), True),
        ("jpeg quality 70", _encode(image.convert("RGB"), "JPEG", quality=70), True),
        ("resized 50%", _encode(image.resize((width // 2, height // 2))), True),
        ("brightness +15", _encode(image.point(lambda p: min(255, p + 15))), True),
        ("brightness -15", _encode(image.point(lambda p: max(0, p - 15))), True),
        ("blur radius 1.0", _encode(image.filter(ImageFilter.GaussianBlur(radius=1.0))), True),
        ("crop 3 percent", _encode(image.crop((int(width * 0.03), int(height * 0.03), int(width * 0.97), int(height * 0.97)))), True),
        ("saved as jpeg then re-read", _encode(Image.open(io.BytesIO(_encode(image.convert("RGB"), "JPEG", quality=85)))), True),
    ]
    return variants


def _negatives(image: Image.Image, seed: int) -> list[tuple[str, bytes]]:
    width, height = image.size
    solid = Image.new("L", (width, height), 128)
    other = _synthetic_image(seed + 10_000)
    inverted = Image.eval(image, lambda p: 255 - p)
    mirrored = image.transpose(Image.FLIP_LEFT_RIGHT)
    gradient = Image.new("L", (width, height))
    gradient_draw = ImageDraw.Draw(gradient)
    for x in range(width):
        gradient_draw.line([(x, 0), (x, height)], fill=int(255 * x / max(1, width - 1)))
    return [
        ("different synthetic image", _encode(other)),
        ("solid gray image", _encode(solid)),
        ("solid black image", _encode(Image.new("L", (width, height), 0))),
        ("solid white image", _encode(Image.new("L", (width, height), 255))),
        ("colour inverted", _encode(inverted)),
        ("mirrored", _encode(mirrored)),
        ("gradient", _encode(gradient)),
    ]


def _sweep(pairs: list[tuple[float, bool]], threshold: float) -> dict:
    confusion = Confusion()
    for similarity, actual in pairs:
        confusion.add(predicted_positive=similarity >= threshold, actual_positive=actual)
    return confusion.as_dict()


def measure_perceptual_accuracy(rounds: int = 24) -> Section:
    pairs: list[tuple[float, bool]] = []
    per_variant: dict[str, Confusion] = {}
    positive_scores: list[float] = []
    negative_scores: list[float] = []

    for seed in range(rounds):
        image = _synthetic_image(seed)
        base_bytes = _encode(image)
        base_hash = dhash_bytes(base_bytes)
        if not base_hash:
            continue
        for label, data, same in _variants(image):
            other_hash = dhash_bytes(data)
            if not other_hash:
                continue
            score = hamming_similarity(base_hash, other_hash)
            pairs.append((score, same))
            positive_scores.append(score)
            per_variant.setdefault(label, Confusion())
            per_variant[label].add(predicted_positive=score >= PERCEPTUAL_THRESHOLD, actual_positive=same)
        for label, data in _negatives(image, seed):
            other_hash = dhash_bytes(data)
            if not other_hash:
                continue
            score = hamming_similarity(base_hash, other_hash)
            pairs.append((score, False))
            negative_scores.append(score)

    shipped = _sweep(pairs, PERCEPTUAL_THRESHOLD)
    sweep = {f"{threshold:.2f}": _sweep(pairs, threshold) for threshold in [0.70, 0.75, 0.80, 0.85, 0.875, 0.90, 0.925, 0.95, 0.975, 1.0]}

    ranking_hits = sum(
        1
        for positive in positive_scores
        for negative in negative_scores
        if positive > negative
    )
    ranking_total = len(positive_scores) * len(negative_scores)
    ranking_accuracy = round(ranking_hits / ranking_total, 4) if ranking_total else 0.0

    worst = sorted(per_variant.items(), key=lambda item: item[1].f1)[:5]
    return Section(
        name="perceptual",
        title="Perceptual duplicate detection accuracy (dHash-64)",
        summary=(
            f"At the shipped threshold {PERCEPTUAL_THRESHOLD}: precision {shipped['precision']}, "
            f"recall {shipped['recall']}, F1 {shipped['f1']} over {shipped['pairs']} labelled pairs."
        ),
        metrics={
            "threshold": PERCEPTUAL_THRESHOLD,
            "shipped_threshold": shipped,
            "threshold_sweep": sweep,
            "pairwise_ranking_accuracy": ranking_accuracy,
            "mean_positive_similarity": round(sum(positive_scores) / len(positive_scores), 4) if positive_scores else 0.0,
            "mean_negative_similarity": round(sum(negative_scores) / len(negative_scores), 4) if negative_scores else 0.0,
            "per_variant": {label: confusion.as_dict() for label, confusion in per_variant.items()},
        },
        tables=[(
            ("Variant", "Pairs", "Precision", "Recall", "F1"),
            [
                (label, str(confusion.as_dict()["pairs"]), str(confusion.precision), str(confusion.recall), str(confusion.f1))
                for label, confusion in sorted(per_variant.items())
            ],
        )],
        notes=[
            "This is the shipped signal behind 'similar content' alerts. It is an evidence indicator, not a finding of infringement.",
            "dHash is a 64-bit structural hash: it is robust to re-encoding, resizing, brightness and mild blur, "
            "and it is blind to colour, to solid-colour images (a known false-positive family), and to mirroring.",
            "The sweep shows the precision/recall trade-off at every threshold so the operating point can be defended with data.",
        ],
    )


def measure_text_accuracy(rounds: int = 40) -> Section:
    base_paragraph = (
        "The ownership certificate binds a sha256 fingerprint to a poseidon commitment and an append only ledger "
        "transaction so that a creator can later prove possession of the private opening without publishing the work. "
        "Every transfer rotates the credential so the previous owner can no longer produce a valid proof. "
    )
    documents: list[tuple[str, str, bool]] = []
    for index in range(rounds):
        rng = random.Random(1000 + index)
        other = " ".join(
            rng.choice(["marketing", "invoice", "recipe", "travel", "lecture", "budget", "lease"])
            for _ in range(60)
        )
        documents.append((f"base-{index}", base_paragraph + f" Document {index} serial {rng.randint(1000, 9999)}.", True))
        documents.append((f"identical-{index}", base_paragraph + f" Document {index} serial {rng.randint(1000, 9999)}.", True))
        documents.append((f"extended-{index}", base_paragraph + " An appendix records the disclosure timeline and the verifier sign off. " + f" Serial {rng.randint(1000, 9999)}.", True))
        documents.append((f"other-{index}", other, False))

    pairs: list[tuple[float, bool]] = []
    positives: list[float] = []
    negatives: list[float] = []
    for i in range(rounds):
        base = documents[i * 4][1]
        for offset in (1, 2):
            other = documents[i * 4 + offset][1]
            score = text_similarity(base, other)
            pairs.append((score, True))
            positives.append(score)
        other = documents[i * 4 + 3][1]
        score = text_similarity(base, other)
        pairs.append((score, False))
        negatives.append(score)

    shipped = _sweep(pairs, TEXT_THRESHOLD)
    sweep = {f"{threshold:.2f}": _sweep(pairs, threshold) for threshold in [0.30, 0.40, 0.50, 0.60, 0.72, 0.80, 0.90]}
    ranking_hits = sum(1 for positive in positives for negative in negatives if positive > negative)
    ranking_total = len(positives) * len(negatives)
    return Section(
        name="text",
        title="Text similarity detection accuracy (4-shingle Jaccard)",
        summary=(
            f"At the shipped threshold {TEXT_THRESHOLD}: precision {shipped['precision']}, "
            f"recall {shipped['recall']}, F1 {shipped['f1']} over {shipped['pairs']} labelled pairs."
        ),
        metrics={
            "threshold": TEXT_THRESHOLD,
            "shipped_threshold": shipped,
            "threshold_sweep": sweep,
            "pairwise_ranking_accuracy": round(ranking_hits / ranking_total, 4) if ranking_total else 0.0,
            "mean_positive_similarity": round(sum(positives) / len(positives), 4) if positives else 0.0,
            "mean_negative_similarity": round(sum(negatives) / len(negatives), 4) if negatives else 0.0,
        },
        notes=[
            "Only applies to text-like assets; images and binaries use the perceptual and exact signals.",
            "Word-level shingles make the signal robust to whitespace and formatting but sensitive to rewording.",
        ],
    )


# --------------------------------------------------------------------------
# 4. proof soundness and completeness
# --------------------------------------------------------------------------


def measure_proof_accuracy(trials: int = 40) -> Section:
    valid_total = 0
    valid_accepted = 0
    invalid_total = 0
    invalid_accepted = 0
    classes: dict[str, dict] = {}

    def record(label: str, accepted: bool) -> None:
        nonlocal invalid_total, invalid_accepted
        invalid_total += 1
        if accepted:
            invalid_accepted += 1
        entry = classes.setdefault(label, {"trials": 0, "accepted": 0})
        entry["trials"] += 1
        if accepted:
            entry["accepted"] += 1

    for index in range(trials):
        fingerprint = hashlib.sha256(f"proof-trial-{index}".encode()).hexdigest()
        registration_id = f"AQ-2026-TRIAL{index:04d}"
        nonce = secrets.token_urlsafe(24)
        commitment = create_commitment(fingerprint)
        secret = commitment["secret_int"]
        blinding = commitment["blinding_int"]
        proof = generate_proof(
            fingerprint,
            registration_id,
            nonce,
            commitment["pedersen_commitment"],
            secret,
            blinding,
        )
        accepted, _ = verify_proof(
            proof, fingerprint, registration_id, nonce, commitment["pedersen_commitment"]
        )
        valid_total += 1
        if accepted:
            valid_accepted += 1

        # soundness: every forgery class must be rejected
        z1 = proof["response"][0]
        flipped_z1 = z1[:-1] + ("0" if z1[-1] != "0" else "1")
        tampered_response = {**proof, "response": [flipped_z1, proof["response"][1]]}
        record("tampered response z1", verify_proof(tampered_response, fingerprint, registration_id, nonce, commitment["pedersen_commitment"])[0])

        tampered_challenge = {**proof, "challenge": "0x" + "0" * 64}
        record("forged challenge", verify_proof(tampered_challenge, fingerprint, registration_id, nonce, commitment["pedersen_commitment"])[0])

        tampered_anchor = {**proof, "anchor": "0x" + "1" * 128}
        record("forged anchor point", verify_proof(tampered_anchor, fingerprint, registration_id, nonce, commitment["pedersen_commitment"])[0])

        wrong_secret = create_commitment(fingerprint)
        forged = generate_proof(
            fingerprint,
            registration_id,
            nonce,
            commitment["pedersen_commitment"],
            wrong_secret["secret_int"],
            wrong_secret["blinding_int"],
        )
        record("wrong secret (forged proof)", verify_proof(forged, fingerprint, registration_id, nonce, commitment["pedersen_commitment"])[0])

        record(
            "wrong file fingerprint",
            verify_proof(proof, hashlib.sha256(b"other-file").hexdigest(), registration_id, nonce, commitment["pedersen_commitment"])[0],
        )
        record(
            "wrong registration id",
            verify_proof(proof, fingerprint, "AQ-2026-OTHER0001", nonce, commitment["pedersen_commitment"])[0],
        )
        record(
            "wrong challenge nonce",
            verify_proof(proof, fingerprint, registration_id, "nonce-does-not-match", commitment["pedersen_commitment"])[0],
        )
        record(
            "wrong commitment",
            verify_proof(proof, fingerprint, registration_id, nonce, "0x" + "2" * 128)[0],
        )

    completeness = round(valid_accepted / valid_total, 4) if valid_total else 0.0
    soundness = round(1 - (invalid_accepted / invalid_total), 4) if invalid_total else 0.0
    return Section(
        name="proof",
        title="Ownership proof accuracy (BN254 Schnorr)",
        summary=(
            f"Completeness {completeness} ({valid_accepted}/{valid_total} valid proofs accepted), "
            f"soundness {soundness} ({invalid_total - invalid_accepted}/{invalid_total} forgeries rejected)."
        ),
        metrics={
            "trials": trials,
            "valid_proofs": valid_total,
            "valid_accepted": valid_accepted,
            "completeness": completeness,
            "invalid_proofs": invalid_total,
            "invalid_accepted": invalid_accepted,
            "soundness": soundness,
            "rejection_rate_by_attack": classes,
        },
        tables=[(
            ("Attack class", "Trials", "Accepted (must be 0)"),
            [
                (label, str(entry["trials"]), str(entry["accepted"]))
                for label, entry in sorted(classes.items())
            ],
        )],
        notes=[
            "Completeness: honest proofs always verify. Soundness: forged proofs never verify.",
            "Soundness here is empirical over the sampled attack classes; the underlying guarantee comes from "
            "the discrete-log hardness of BN254 and the Fiat-Shamir binding of the challenge.",
        ],
    )


# --------------------------------------------------------------------------
# 5. authorization matrix accuracy (live API)
# --------------------------------------------------------------------------


def _register(client, display_name: str, account_type: str = "individual", organization_name: str | None = None):
    email = f"acc-{secrets.token_hex(6)}@authentiq.dev"
    payload = {
        "display_name": display_name,
        "email": email,
        "password": "Authentiq!Acc2026",
        "confirm_password": "Authentiq!Acc2026",
        "account_type": account_type,
        "accept_terms": True,
    }
    if organization_name:
        payload["organization_name"] = organization_name
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    return {
        "email": email,
        "id": data["user"]["id"],
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
    }


def _upload_and_register(client, headers, content: bytes, title: str):
    sha = hashlib.sha256(content).hexdigest()
    initiate_response = client.post(
        "/api/uploads/initiate",
        headers=headers,
        json={
            "filename": "artifact.txt",
            "size_bytes": len(content),
            "mime_type": "text/plain",
            "total_chunks": 1,
            "chunk_size": 65536,
        },
    )
    assert initiate_response.status_code == 200, initiate_response.text
    initiate = initiate_response.json()
    chunk = client.post(
        f"/api/uploads/{initiate['upload_id']}/chunk",
        headers=headers,
        data={"chunk_index": "0", "sha256": sha},
        files={"file": ("artifact.txt", content, "text/plain")},
    )
    assert chunk.status_code == 200, chunk.text
    complete = client.post(
        f"/api/uploads/{initiate['upload_id']}/complete", headers=headers, data={"client_sha256": sha}
    )
    assert complete.status_code == 200, complete.text
    created = client.post(
        "/api/registrations",
        headers=headers,
        json={"upload_id": initiate["upload_id"], "title": title, "asset_type": "document", "privacy": "private"},
    )
    assert created.status_code == 201, created.text
    return created.json()["registration"], sha


def measure_authorization_accuracy() -> Section:
    from fastapi.testclient import TestClient

    from app.main import app

    results: list[dict] = []
    with TestClient(app) as client:
        owner = _register(client, "Owner Creator", account_type="organization", organization_name="Accuracy Org")
        colleague = _register(client, "Org Colleague")
        outsider = _register(client, "Outside User")
        recipient = _register(client, "Incoming Recipient")

        # make the colleague a member of the owner's organization
        invitation = client.post(
            "/api/settings/organization/invitations",
            headers=owner["headers"],
            json={"email": colleague["email"], "role": "org_member"},
        )
        assert invitation.status_code == 201, invitation.text
        client.post(
            "/api/settings/organization/invitations/accept",
            headers=colleague["headers"],
            json={"token": invitation.json()["invitation"]["invite_token"]},
        )

        registration, sha = _upload_and_register(client, owner["headers"], b"accuracy corpus payload", "Accuracy Record")
        identifier = registration["registration_id"]
        spare, _ = _upload_and_register(client, owner["headers"], b"second accuracy payload", "Spare Record")
        spare_identifier = spare["registration_id"]

        # a pending incoming transfer gives the recipient read access
        transfer = client.post(
            "/api/transfers",
            headers=owner["headers"],
            json={"registration_id": identifier, "recipient_email": recipient["email"]},
        ).json()
        client.post(f"/api/transfers/{transfer['id']}/accept", headers=recipient["headers"])

        # site admin
        site_admin = _register(client, "Site Admin")
        from app.core.database import SessionLocal
        from app.models import User

        with SessionLocal() as db:
            account = db.get(User, site_admin["id"])
            account.role = "site_admin"
            db.commit()

        cases: list[tuple[str, str, str, int]] = []

        def probe(label: str, actor, method: str, path: str, expected: int, **kwargs) -> None:
            headers = actor["headers"] if actor else {}
            response = client.request(method, path, headers=headers, **kwargs)
            cases.append((label, method, path, expected))
            results.append(
                {
                    "case": label,
                    "method": method,
                    "path": path,
                    "expected_status": expected,
                    "actual_status": response.status_code,
                    "match": response.status_code == expected,
                }
            )

        probe("owner reads own record", owner, "GET", f"/api/registrations/{identifier}", 200)
        probe("organization member reads record", colleague, "GET", f"/api/registrations/{identifier}", 200)
        probe("pending recipient reads record", recipient, "GET", f"/api/registrations/{identifier}", 200)
        probe("outsider is denied record", outsider, "GET", f"/api/registrations/{identifier}", 403)
        probe("anonymous is refused record", None, "GET", f"/api/registrations/{identifier}", 401)
        probe("owner downloads original", owner, "GET", f"/api/registrations/{identifier}/file", 200)
        probe("outsider cannot download original", outsider, "GET", f"/api/registrations/{identifier}/file", 403)
        probe("owner reveals private key", owner, "GET", f"/api/registrations/{identifier}/verification-key", 200)
        probe("pending recipient cannot reveal private key", recipient, "GET", f"/api/registrations/{identifier}/verification-key", 403)
        probe("org member cannot reveal private key", colleague, "GET", f"/api/registrations/{identifier}/verification-key", 403)
        probe(
            "owner proposes a transfer",
            owner,
            "POST",
            "/api/transfers",
            201,
            json={"registration_id": spare_identifier, "recipient_email": outsider["email"]},
        )
        probe(
            "pending recipient cannot propose a transfer",
            recipient,
            "POST",
            "/api/transfers",
            403,
            json={"registration_id": identifier, "recipient_email": outsider["email"]},
        )
        probe("site admin opens the console", site_admin, "GET", "/api/admin/users", 200)
        probe("owner is denied the console", owner, "GET", "/api/admin/users", 403)
        probe("anonymous is refused the console", None, "GET", "/api/admin/users", 401)
        probe("owner reads the dashboard", owner, "GET", "/api/dashboard/summary", 200)
        probe("any account gets its own dashboard", outsider, "GET", "/api/dashboard/summary", 200)
        probe(
            "public anonymous challenge is open",
            None,
            "POST",
            "/api/public/verify/anonymous/challenge",
            200,
            json={"registration_id": identifier, "file_sha256": sha},
        )
        probe(
            "public fingerprint existence check is open",
            None,
            "POST",
            "/api/public/fingerprints/check",
            200,
            json={"sha256": sha},
        )
        probe(
            "public records listing is open",
            None,
            "GET",
            "/api/public/records",
            200,
        )

    matches = sum(1 for item in results if item["match"])
    total = len(results)
    mismatches = [item for item in results if not item["match"]]
    return Section(
        name="authorization",
        title="Authorization decision accuracy (live API)",
        summary=(
            f"{matches}/{total} authorization decisions matched the expected policy "
            f"({round(matches / total, 4) if total else 0})."
        ),
        metrics={
            "cases": total,
            "matched": matches,
            "mismatched": len(mismatches),
            "accuracy": round(matches / total, 4) if total else 0.0,
            "mismatches": mismatches,
            "decisions": results,
        },
        tables=[(
            ("Case", "Method", "Path", "Expected", "Actual", "Match"),
            [
                (
                    item["case"],
                    item["method"],
                    item["path"],
                    str(item["expected_status"]),
                    str(item["actual_status"]),
                    "yes" if item["match"] else "NO",
                )
                for item in results
            ],
        )],
        notes=[
            "Each case is a real HTTP request against the running API, not a unit test of a helper.",
            "Expected values encode the documented policy: owner, organization member, pending recipient, outsider, anonymous, and site admin.",
        ],
    )


# --------------------------------------------------------------------------
# 6. ledger tamper detection
# --------------------------------------------------------------------------


def measure_ledger_integrity() -> Section:
    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.ledger import ledger_service
    from app.services.integrity import ledger_truncation_check

    path = settings.ledger_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

    with SessionLocal() as db:
        for index in range(6):
            ledger_service._record(
                db,
                "creation_registered",
                "actor",
                "registration",
                f"AQ-2026-{index:04d}",
                {"index": index},
            )
        db.commit()

    clean = ledger_service.audit()
    original_text = path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in original_text.splitlines() if line.strip()]

    mutated_detected = 0
    mutated_total = 0
    detection_by_class: dict[str, dict] = {}
    for index, record in enumerate(records):
        for label, mutation in (
            ("payload edited", {"payload": {"index": 999}}),
            ("record hash edited", {"record_hash": "0" * 64}),
            ("payload digest edited", {"payload_digest": "1" * 64}),
            ("block number edited", {"block_number": 42}),
        ):
            broken = {**record, **mutation}
            lines = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in records]
            lines[index] = json.dumps(broken, sort_keys=True, separators=(",", ":"))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            report = ledger_service.audit()
            mutated_total += 1
            entry = detection_by_class.setdefault(label, {"trials": 0, "detected": 0})
            entry["trials"] += 1
            if not report["valid"]:
                mutated_detected += 1
                entry["detected"] += 1

    path.write_text(original_text, encoding="utf-8")

    # truncation: the hash chain alone cannot see a removed tail, the database copy can
    lines = original_text.splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    chain_only = ledger_service.audit()
    chain_only_detected = not chain_only["valid"]
    with SessionLocal() as db:
        cross_check = ledger_truncation_check(db, ledger_service.audit())
    cross_check_detected = bool(cross_check)
    path.write_text(original_text, encoding="utf-8")

    detection_rate = round(mutated_detected / mutated_total, 4) if mutated_total else 0.0
    return Section(
        name="ledger",
        title="Ledger and audit tamper detection",
        summary=(
            f"Clean chain valid: {clean['valid']}. "
            f"Detection rate for silent edits: {detection_rate} ({mutated_detected}/{mutated_total}). "
            f"Tail removal seen by the chain alone: {chain_only_detected}; seen by the database cross-check: {cross_check_detected}."
        ),
        metrics={
            "clean_chain_valid": clean["valid"],
            "clean_records": clean["records"],
            "mutations_tested": mutated_total,
            "mutations_detected": mutated_detected,
            "detection_rate": detection_rate,
            "truncation_detected_by_chain": chain_only_detected,
            "truncation_detected_by_database_cross_check": cross_check_detected,
            "truncation_issues": cross_check,
            "detection_by_class": detection_by_class,
        },
        tables=[(
            ("Tamper class", "Trials", "Detected"),
            [
                (label, str(entry["trials"]), str(entry["detected"]))
                for label, entry in sorted(detection_by_class.items())
            ],
        )],
        notes=[
            "Every record carries the hash of its predecessor, so an edit breaks the chain immediately.",
            "Removing the newest record leaves a structurally valid chain, so the file alone cannot prove it. "
            "The shipped mitigation is the independent database copy of every ledger record: the Integrity Center "
            "compares the record count and the head hash and reports a truncation.",
            "The audit log uses the same chaining idea over a separate table.",
        ],
    )


# --------------------------------------------------------------------------
# report rendering
# --------------------------------------------------------------------------


def render_markdown(sections: list[Section], generated_at: str) -> str:
    lines = [
        "# AUTHENTIQ accuracy report",
        "",
        f"Generated {generated_at} by `python -m scripts.accuracy_report`.",
        "",
        "AUTHENTIQ is not a trained model, so it has no single accuracy number. It is a stack of "
        "measurable components, and each one is measured here against labelled ground truth with the "
        "same code the product runs.",
        "",
        "| Component | Headline result |",
        "| --- | --- |",
    ]
    for section in sections:
        headline = section.summary.replace("\n", " ")
        lines.append(f"| {section.title} | {headline} |")
    lines.append("")

    for section in sections:
        lines.append(f"## {section.title}")
        lines.append("")
        lines.append(section.summary)
        lines.append("")
        for table in section.tables:
            header, rows = table
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join("---" for _ in header) + " |")
            for row in rows:
                lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
            lines.append("")
        if section.name in {"perceptual", "text"}:
            sweep = section.metrics.get("threshold_sweep", {})
            if sweep:
                lines.append("| Threshold | Precision | Recall | F1 | Accuracy |")
                lines.append("| --- | --- | --- | --- | --- |")
                for threshold, values in sweep.items():
                    lines.append(
                        f"| {threshold} | {values['precision']} | {values['recall']} | {values['f1']} | {values['accuracy']} |"
                    )
                lines.append("")
        if section.name == "authorization":
            lines.append("| Case | Method | Path | Expected | Actual | Match |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for item in section.metrics.get("decisions", []):
                lines.append(
                    f"| {item['case']} | {item['method']} | `{item['path']}` | {item['expected_status']} | "
                    f"{item['actual_status']} | {'yes' if item['match'] else 'NO'} |"
                )
            lines.append("")
        if section.notes:
            lines.append("**How to read this**")
            lines.append("")
            for note in section.notes:
                lines.append(f"- {note}")
            lines.append("")

    lines.append("## How to reproduce")
    lines.append("")
    lines.append("```powershell")
    lines.append("cd backend")
    lines.append(".\\.venv\\Scripts\\python.exe -m scripts.accuracy_report")
    lines.append("```")
    lines.append("")
    lines.append("The harness writes the raw numbers to `storage/accuracy-report.json`. The same corpus "
                 "generation and thresholds are covered by `backend/tests/test_accuracy_report.py`, so a "
                 "regression in detection quality fails the test suite instead of silently shipping.")
    lines.append("")
    lines.append("## Honest limits")
    lines.append("")
    lines.append("- Similarity signals are indicators, not legal findings of infringement.")
    lines.append("- The perceptual signal is a 64-bit structural hash: robust to re-encoding and resizing, "
                 "blind to colour and insensitive to mirroring. The measured false-positive families are "
                 "listed above.")
    lines.append("- Proof soundness is empirically sampled per attack class; the formal guarantee comes from "
                 "the discrete-log assumption of BN254.")
    lines.append("- The AI-provenance analyzer is metadata inspection only and reports no classifier score. "
                 "AUTHENTIQ does not fabricate a detection result when no model is configured.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure AUTHENTIQ component accuracy")
    parser.add_argument("--json", default=str(ROOT.parent / "storage" / "accuracy-report.json"))
    parser.add_argument("--markdown", default=str(ROOT.parent / "docs" / "ACCURACY.md"))
    parser.add_argument("--trials", type=int, default=40)
    args = parser.parse_args()

    from datetime import datetime, timezone

    generated_at = datetime.now(timezone.utc).isoformat()
    sections = [
        measure_fingerprint_accuracy(),
        measure_perceptual_accuracy(),
        measure_text_accuracy(),
        measure_proof_accuracy(trials=args.trials),
        measure_authorization_accuracy(),
        measure_ledger_integrity(),
    ]

    payload = {
        "generated_at": generated_at,
        "application": "AUTHENTIQ",
        "note": "AUTHENTIQ is a cryptographic ownership stack, not a trained model. Accuracy is reported per measurable component.",
        "sections": {section.name: {"title": section.title, "summary": section.summary, "metrics": section.metrics} for section in sections},
    }

    json_path = Path(args.json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    markdown_path = Path(args.markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(sections, generated_at), encoding="utf-8")

    for section in sections:
        print(f"{section.title}: {section.summary}")
    print()
    print(f"json    -> {json_path}")
    print(f"markdown-> {markdown_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        shutil.rmtree(WORK_ROOT, ignore_errors=True)
