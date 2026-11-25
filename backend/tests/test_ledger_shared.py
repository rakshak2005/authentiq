"""The ledger file and the database copy of the ledger must agree.

More than one backend can share one database. Each keeps its own append-only
file, so the file can be missing records another instance wrote. That is not
tampering, and the integrity centre must not report it as such. The reverse
is tampering: a record in the file that the database never confirmed, or a
record in the database that continues a chain the file no longer holds.
"""

from app.core.config import settings
from app.core.database import SessionLocal
from app.ledger import ledger_service
from app.models import LedgerTransaction
from app.services.integrity import ledger_truncation_check


def _record(db, tx_type="probe"):
    ledger_service._record(db, tx_type, "actor", "registration", "AQ-2026-PROBE", {"probe": True})
    db.commit()


def test_a_record_the_file_never_held_is_not_tampering():
    """Another backend instance wrote a row the local file never saw."""
    path = settings.ledger_file
    original = path.read_text(encoding="utf-8")
    try:
        with SessionLocal() as db:
            _record(db, "local_probe")

        # A row from another instance: it is in the database but not in the file.
        with SessionLocal() as db:
            row = LedgerTransaction(
                tx_id="aqtx_foreign_00000001",
                block_number=99,
                tx_type="creation_registered",
                entity_type="registration",
                entity_id="AQ-2026-FOREIGN",
                payload_digest="0" * 64,
                prev_hash="f" * 64,
                record_hash="e" * 64,
                payload={"registration_id": "AQ-2026-FOREIGN"},
                mode="simulation",
                network="AUTHENTIQ Local Ledger",
                status="confirmed",
            )
            db.add(row)
            db.commit()

        with SessionLocal() as db:
            issues = ledger_truncation_check(db, ledger_service.audit())

        assert issues == [], f"a shared database must not look like tampering: {issues}"
    finally:
        path.write_text(original, encoding="utf-8")
        with SessionLocal() as db:
            db.query(LedgerTransaction).filter(LedgerTransaction.tx_id == "aqtx_foreign_00000001").delete()
            db.commit()


def test_a_truncated_tail_is_reported():
    path = settings.ledger_file
    original = path.read_text(encoding="utf-8")
    try:
        with SessionLocal() as db:
            _record(db, "tail_probe")

        lines = original.splitlines() + path.read_text(encoding="utf-8").splitlines()[len(original.splitlines()) :]
        path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

        with SessionLocal() as db:
            issues = ledger_truncation_check(db, ledger_service.audit())

        assert issues, "a truncated ledger file must be reported against the database copy"
    finally:
        path.write_text(original, encoding="utf-8")


def test_an_emptied_file_is_reported():
    path = settings.ledger_file
    original = path.read_text(encoding="utf-8")
    try:
        with SessionLocal() as db:
            _record(db, "empty_probe")

        path.write_text("", encoding="utf-8")

        with SessionLocal() as db:
            issues = ledger_truncation_check(db, ledger_service.audit())

        assert issues, "an emptied ledger file must be reported against the database copy"
    finally:
        path.write_text(original, encoding="utf-8")
