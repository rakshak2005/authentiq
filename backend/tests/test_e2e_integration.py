"""
End-to-end integration tests for AUTHENTIQ.

Covers the complete journey:
1. User registration
2. File upload and fingerprinting (SHA-256)
3. Ownership registration
4. Zero-knowledge proof generation
5. Silent sharing (proof package)
6. Independent public verification
7. Dispute creation and resolution

Uses the existing test client and helpers. No real private keys, no mainnet,
no external services.
"""

import hashlib

from fastapi.testclient import TestClient

from app.models import User
from tests.helpers import register_user, upload_file, create_registration, PASSWORD

# ---------------------------------------------------------------------------
# Helper: full registration flow
# ---------------------------------------------------------------------------


def register_creation_full(client, headers, content=b"AUTHENTIQ end-to-end test content"):
    """Complete registration: upload file, create registration record."""
    upload = upload_file(client, headers, content, filename="e2e-artifact.txt")
    response = client.post(
        "/api/registrations",
        headers=headers,
        json={
            "upload_id": upload["upload_id"],
            "title": "E2E Test Artifact",
            "description": "End-to-end integration test artifact",
            "asset_type": "document",
            "privacy": "private",
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    # The response wraps registration data under "registration" key
    reg_data = data["registration"]
    data["registration_id"] = reg_data["registration_id"]
    data["sha256"] = reg_data["sha256"]
    data["status"] = reg_data["status"]
    data["ledger_mode"] = reg_data["ledger_mode"]
    data["ledger_tx_id"] = reg_data["ledger_tx_id"]
    data["upload"] = upload
    data["content"] = content
    data["content_sha256"] = hashlib.sha256(content).hexdigest()
    return data


# ---------------------------------------------------------------------------
# Test: Full end-to-end journey
# ---------------------------------------------------------------------------


def test_end_to_end_registration_to_dispute(client):
    """Complete journey: register -> fingerprint -> prove -> share -> verify -> dispute."""

    # === Step 1: User registration ===
    creator = register_user(client, display_name="E2E Creator")
    creator_headers = creator["headers"]
    creator_email = creator["email"]

    # === Step 2: File upload + fingerprinting + ownership registration ===
    registration = register_creation_full(client, creator_headers)
    reg_id = registration["registration_id"]
    content_sha256 = registration["content_sha256"]
    assert registration["sha256"] == content_sha256
    assert registration["status"] == "registered"

    # === Step 3: Proof generation ===
    # Create a challenge
    challenge_resp = client.post(
        "/api/zkp/challenge",
        headers=creator_headers,
        json={"registration_id": reg_id, "purpose": "proof"},
    )
    assert challenge_resp.status_code == 200, challenge_resp.text
    challenge = challenge_resp.json()
    assert challenge["registration_id"] == reg_id
    assert "nonce" in challenge

    # Generate the proof
    gen_resp = client.post(
        "/api/zkp/generate",
        headers=creator_headers,
        json={
            "registration_id": reg_id,
            "challenge_id": challenge["challenge_id"],
            "file_sha256": content_sha256,
        },
    )
    assert gen_resp.status_code == 200, gen_resp.text
    gen_data = gen_resp.json()
    assert gen_data["proof_id"] is not None
    assert gen_data["proof"] is not None
    assert gen_data["public_signals"] is not None

    # Verify the proof
    verify_resp = client.post(
        "/api/zkp/verify",
        headers=creator_headers,
        json={
            "registration_id": reg_id,
            "nonce": challenge["nonce"],
            "proof": gen_data["proof"],
            "public_signals": gen_data["public_signals"],
        },
    )
    assert verify_resp.status_code == 200, verify_resp.text
    verify_data = verify_resp.json()
    assert verify_data["valid"] is True
    assert verify_data["registration_id"] == reg_id

    # Confirm registration status changed to verified
    reg_detail = client.get(f"/api/registrations/{reg_id}", headers=creator_headers)
    assert reg_detail.status_code == 200
    assert reg_detail.json()["status"] == "verified"

    # === Step 4: Silent sharing (create verification package) ===
    share_resp = client.post(
        "/api/sharing/create",
        headers=creator_headers,
        json={
            "registration_id": reg_id,
            "expires_in_hours": 72,
            "max_uses": 1,
            "message": "Please verify my ownership of this artifact",
            "disclosure": {
                "show_reference": True,
                "show_registration_date": True,
                "show_fingerprint": True,
                "show_organization": False,
                "anonymous": True,
            },
        },
    )
    assert share_resp.status_code == 201, share_resp.text
    share_data = share_resp.json()
    verification_id = share_data["verification_id"]
    verification_url = share_data["verification_url"]
    proof_package = share_data["proof_package"]
    assert verification_id is not None
    assert proof_package is not None
    assert proof_package["proof"] is not None
    assert proof_package["public_signals"] is not None

    # === Step 5: Independent public verification (no login) ===
    # First, look up the public record
    lookup_resp = client.get(f"/api/public/verify/anonymous/lookup/{reg_id}")
    assert lookup_resp.status_code == 200, lookup_resp.text
    lookup_data = lookup_resp.json()
    assert lookup_data["registration_reference"] == reg_id
    assert lookup_data["fingerprint"] == content_sha256
    assert lookup_data["commitment"] is not None

    # Get the public verification page (GET)
    public_get = client.get(f"/api/public/verify/{verification_id}")
    assert public_get.status_code == 200, public_get.text
    public_data = public_get.json()
    assert public_data["verification_id"] == verification_id
    assert public_data["requires_proof"] is True

    # Submit the proof package (POST)
    public_verify_resp = client.post(
        f"/api/public/verify/{verification_id}",
        json={"proof_package": proof_package},
    )
    assert public_verify_resp.status_code == 200, public_verify_resp.text
    public_verify_data = public_verify_resp.json()
    assert public_verify_data["valid"] is True
    assert public_verify_data["verification_id"] == verification_id
    assert public_verify_data["registration_reference"] == reg_id

    # === Step 6: Dispute creation and resolution ===
    # A second user disputes the ownership
    disputer = register_user(client, display_name="Disputing User")
    disputer_headers = disputer["headers"]

    dispute_resp = client.post(
        "/api/disputes",
        headers=disputer_headers,
        json={
            "registration_id": reg_id,
            "reason": "I am the original creator of this work",
            "description": "I created this artifact before the current registrant and have evidence of prior creation.",
        },
    )
    assert dispute_resp.status_code == 201, dispute_resp.text
    dispute_data = dispute_resp.json()
    assert dispute_data["dispute_ref"] is not None
    assert dispute_data["status"] == "open"

    # Make the owner a verifier so they can resolve disputes
    from app.core.database import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        owner_user = db.get(User, creator["user"]["id"])
        owner_user.role = "verifier"
        db.commit()

    # Resolve the dispute as verifier
    resolve_resp = client.post(
        f"/api/disputes/{dispute_data['id']}/status",
        headers=creator_headers,
        json={
            "status": "resolved",
            "resolution": "The disputer provided no verifiable proof. The registered SHA-256 fingerprint and ZKP proof confirm the current registrant's ownership.",
            "determination": "respondent_wins",
            "resolution_reason": "Disputer failed to provide verifiable proof of prior creation. Registrant holds the earliest registration and a valid ZKP proof.",
        },
    )
    assert resolve_resp.status_code == 200, resolve_resp.text
    resolve_data = resolve_resp.json()
    assert resolve_data["status"] == "resolved"
    assert resolve_data["determination"] == "respondent_wins"

    # Verify the dispute is resolved
    dispute_detail = client.get(f"/api/disputes/{dispute_data['id']}", headers=creator_headers)
    assert dispute_detail.status_code == 200
    assert dispute_detail.json()["status"] == "resolved"
    assert dispute_detail.json()["determination"] == "respondent_wins"


# ---------------------------------------------------------------------------
# Test: Invalid proof is rejected during verification
# ---------------------------------------------------------------------------


def test_end_to_end_invalid_proof_rejected(client):
    """An invalid proof package must be rejected during public verification."""

    # Register a user and creation
    creator = register_user(client, display_name="Invalid Proof Creator")
    registration = register_creation_full(client, creator["headers"])
    reg_id = registration["registration_id"]
    content_sha256 = registration["content_sha256"]

    # Create a sharing link
    share_resp = client.post(
        "/api/sharing/create",
        headers=creator["headers"],
        json={
            "registration_id": reg_id,
            "expires_in_hours": 72,
            "max_uses": 1,
            "disclosure": {"show_reference": True, "show_registration_date": True, "show_fingerprint": True},
        },
    )
    assert share_resp.status_code == 201
    verification_id = share_resp.json()["verification_id"]

    # Submit an invalid proof package (garbage JSON)
    invalid_resp = client.post(
        f"/api/public/verify/{verification_id}",
        json={"proof_package": {"proof": {"invalid": "proof"}, "public_signals": {}}},
    )
    # Should return 200 with valid=false, or 422 for malformed input
    assert invalid_resp.status_code in (200, 422), invalid_resp.text
    if invalid_resp.status_code == 200:
        data = invalid_resp.json()
        assert data["valid"] is False


# ---------------------------------------------------------------------------
# Test: Dispute without proof is resolved against claimant
# ---------------------------------------------------------------------------


def test_end_to_end_dispute_without_proof(client):
    """A dispute where the claimant has no proof should be resolved against them."""

    # Register owner and creation
    owner = register_user(client, display_name="Rightful Owner")
    registration = register_creation_full(client, owner["headers"])
    reg_id = registration["registration_id"]

    # Generate a valid proof for the owner
    challenge_resp = client.post(
        "/api/zkp/challenge",
        headers=owner["headers"],
        json={"registration_id": reg_id, "purpose": "proof"},
    )
    challenge = challenge_resp.json()
    gen_resp = client.post(
        "/api/zkp/generate",
        headers=owner["headers"],
        json={
            "registration_id": reg_id,
            "challenge_id": challenge["challenge_id"],
            "file_sha256": registration["content_sha256"],
        },
    )
    gen_data = gen_resp.json()
    verify_resp = client.post(
        "/api/zkp/verify",
        headers=owner["headers"],
        json={
            "registration_id": reg_id,
            "nonce": challenge["nonce"],
            "proof": gen_data["proof"],
            "public_signals": gen_data["public_signals"],
        },
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["valid"] is True

    # A claimant without proof opens a dispute
    claimant = register_user(client, display_name="Unproven Claimant")
    dispute_resp = client.post(
        "/api/disputes",
        headers=claimant["headers"],
        json={
            "registration_id": reg_id,
            "reason": "I claim this is my work",
            "description": "I believe this artifact was created by me first.",
        },
    )
    assert dispute_resp.status_code == 201
    dispute_id = dispute_resp.json()["id"]

    # Make the owner a verifier so they can resolve disputes
    from app.core.database import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        owner_user = db.get(User, owner["user"]["id"])
        owner_user.role = "verifier"
        db.commit()

    # Owner resolves against the claimant
    resolve_resp = client.post(
        f"/api/disputes/{dispute_id}/status",
        headers=owner["headers"],
        json={
            "status": "resolved",
            "resolution": "Claimant has no verifiable proof. Owner holds valid ZKP proof and earliest registration.",
            "determination": "respondent_wins",
            "resolution_reason": "Claimant provided no ZKP proof or evidence of prior creation.",
        },
    )
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["determination"] == "respondent_wins"

