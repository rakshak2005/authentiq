"""Rebase the workspace timeline onto a target calendar day.

A demo workspace is built while the team works on it, so the same workspace is
often shown on a later day. Every record then carries the date it was created
on, and the whole product reads as stale: registrations, teams, alerts,
disputes, proofs, audit entries and ledger receipts all show yesterday.

This tool moves the timeline onto the day of the demo. It does not invent
events and it does not touch the declared creation date of a work (the day the
author says the work itself was made). It only re-dates the *system* events:

  * every system timestamp is mapped onto the target day,
  * the order of the events and the gaps between them are preserved,
  * the audit hash chain and the append-only ledger chain are rebuilt so the
    integrity centre still reports "Intact",
  * a JSON backup of every touched table and of the ledger file is written
    before anything is changed.

Run with:

    python -m scripts.rebase_timestamps --target-date 2026-11-12
    python -m scripts.rebase_timestamps --target-date 2026-11-12 --dry-run

With no ``--target-date`` the current local day is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import DateTime, bindparam, func, select, text, update
from sqlalchemy import inspect

from app.core.config import settings
from app.core.database import SessionLocal
from app.ledger.simulation import GENESIS_HASH, canonical_json, digest
from app.models import AuditLog, Base, LedgerTransaction
from app.services.audit import GENESIS_AUDIT_HASH, _audit_timestamp, _canonical

# Columns that record when the *work* was made, not when the platform acted.
# They are declared by the author and must survive the rebase untouched.
DECLARED_DATE_COLUMNS = {
    ("registrations", "creation_timestamp"),
    ("ai_provenance", "creation_date"),
}

ISO_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


@dataclass
class Rebase:
    """Affine map that moves a timeline onto the target day."""

    origin: datetime
    target_start: datetime
    scale: float

    def apply(self, value: datetime) -> datetime:
        moment = _aware(value)
        seconds = (moment - self.origin).total_seconds() * self.scale
        return self.target_start + timedelta(seconds=seconds)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_iso(value: str) -> datetime | None:
    text_value = value.strip().replace(" ", "T")
    if text_value.endswith("Z"):
        text_value = text_value[:-1] + "+00:00"
    try:
        return _aware(datetime.fromisoformat(text_value))
    except ValueError:
        return None


def _rebase_payload(value, rebase: Rebase):
    """Shift every timestamp embedded in a ledger payload."""
    if isinstance(value, str):
        if ISO_LIKE.match(value):
            parsed = _parse_iso(value)
            if parsed is not None:
                return rebase.apply(parsed).isoformat()
        return value
    if isinstance(value, list):
        return [_rebase_payload(item, rebase) for item in value]
    if isinstance(value, dict):
        return {key: _rebase_payload(item, rebase) for key, item in value.items()}
    return value


def _timestamp_columns():
    """Every system timestamp column, discovered from the model metadata."""
    found = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if not isinstance(column.type, DateTime) or not column.type.timezone:
                continue
            if (table.name, column.name) in DECLARED_DATE_COLUMNS:
                continue
            found.append((table, column))
    return found


def _dataset_span(db, columns):
    """The extent of the recorded history.

    Only values that are already in the past count. Expiry columns point weeks
    into the future and would otherwise stretch the history and squash every
    event into a few minutes.
    """
    now = datetime.now(timezone.utc)
    lowest = None
    highest = None
    for table, column in columns:
        try:
            row = db.execute(select(func.min(column), func.max(column))).one()
        except Exception:
            db.rollback()
            continue
        for value in row:
            if value is None:
                continue
            moment = _aware(value)
            if moment > now:
                continue
            if lowest is None or moment < lowest:
                lowest = moment
            if highest is None or moment > highest:
                highest = moment
    return lowest, highest


def _local_zone(name: str | None):
    if not name or name.lower() == "local":
        return datetime.now().astimezone().tzinfo
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception as exc:  # pragma: no cover - depends on the host tz database
        raise SystemExit(f"Unknown timezone {name!r}. Use an IANA name such as Asia/Kolkata.") from exc


def _day_start(target: date, zone) -> datetime:
    return datetime.combine(target, time.min, tzinfo=zone).astimezone(timezone.utc)


def _backup(db, columns, ledger_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    payload = {"tables": {}}
    tables = sorted({table.name for table, _ in columns})
    for name in tables:
        table = Base.metadata.tables[name]
        try:
            rows = db.execute(select(table)).mappings().all()
        except Exception:
            db.rollback()
            continue
        payload["tables"][name] = [dict(row) for row in rows]
    backup_file = backup_dir / "tables.json"
    backup_file.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    if ledger_path.exists():
        (backup_dir / "ledger.jsonl").write_text(ledger_path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_file


def _read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def _restore(db, backup_dir: Path, ledger_path: Path) -> None:
    """Put the tables and the ledger file back the way the backup found them."""
    payload = json.loads((backup_dir / "tables.json").read_text(encoding="utf-8"))
    for name, rows in payload["tables"].items():
        table = Base.metadata.tables.get(name)
        if table is None:
            continue
        db.execute(table.delete())
        for row in rows:
            values = dict(row)
            for column in table.columns:
                if isinstance(column.type, DateTime) and isinstance(values.get(column.key), str):
                    parsed = _parse_iso(values[column.key])
                    if parsed is not None:
                        values[column.key] = parsed
            db.execute(table.insert().values(values))
    db.commit()
    ledger_backup = backup_dir / "ledger.jsonl"
    if ledger_backup.exists():
        ledger_path.write_text(ledger_backup.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Restored {len(payload['tables'])} tables and the ledger file from {backup_dir}")


def _write_ledger(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".rebase")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(canonical_json(record) + "\n")
    temporary.replace(path)


def _rebuild_audit_chain(db) -> int:
    entries = db.execute(select(AuditLog).order_by(AuditLog.created_at.asc(), AuditLog.id.asc())).scalars().all()
    previous = GENESIS_AUDIT_HASH
    for entry in entries:
        body = {
            "event_id": entry.event_id,
            "actor_id": entry.actor_id,
            "actor_ref": entry.actor_ref,
            "action": entry.action,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "metadata": entry.event_metadata or {},
            "created_at": _audit_timestamp(entry.created_at),
        }
        entry.prev_hash = previous
        entry.record_hash = hashlib.sha256((previous + _canonical(body)).encode("utf-8")).hexdigest()
        previous = entry.record_hash
    db.flush()
    return len(entries)


def _rebuild_ledger(db, path: Path, rebase: Rebase) -> tuple[list[dict], int]:
    records = _read_ledger(path)
    previous = GENESIS_HASH
    for record in records:
        stamp = _parse_iso(str(record.get("timestamp", "")))
        if stamp is not None:
            record["timestamp"] = rebase.apply(stamp).isoformat()
        payload = _rebase_payload(record.get("payload") or {}, rebase)
        record["payload"] = payload
        record["payload_digest"] = digest(payload)
        record["prev_hash"] = previous
        candidate = {key: value for key, value in record.items() if key != "record_hash"}
        record["record_hash"] = digest(candidate)
        previous = record["record_hash"]

    rows_updated = 0
    for record in records:
        row = db.execute(
            select(LedgerTransaction).where(LedgerTransaction.tx_id == record["tx_id"])
        ).scalar_one_or_none()
        if row is None:
            continue
        stamp = _parse_iso(str(record.get("timestamp", "")))
        if stamp is not None:
            row.timestamp = stamp
        row.payload = record.get("payload")
        row.payload_digest = record.get("payload_digest") or ""
        row.prev_hash = record.get("prev_hash") or ""
        row.record_hash = record.get("record_hash") or ""
        rows_updated += 1
    db.flush()
    return records, rows_updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Move the workspace timeline onto a target day.")
    parser.add_argument("--target-date", help="Target calendar day as YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--timezone", default="local", help="IANA timezone used to resolve the target day.")
    parser.add_argument("--dry-run", action="store_true", help="Report the plan without writing anything.")
    parser.add_argument("--backup-dir", default=None, help="Directory for the JSON backup.")
    parser.add_argument("--restore", default=None, help="Restore a backup directory and exit.")
    arguments = parser.parse_args()

    zone = _local_zone(arguments.timezone)
    ledger_path = settings.ledger_file

    if arguments.restore:
        backup_dir = Path(arguments.restore)
        with SessionLocal() as db:
            _restore(db, backup_dir, ledger_path)
        return

    if arguments.target_date:
        target = date.fromisoformat(arguments.target_date)
    else:
        target = datetime.now(zone).date()

    columns = _timestamp_columns()
    ledger_path = settings.ledger_file

    with SessionLocal() as db:
        lowest, highest = _dataset_span(db, columns)
        if lowest is None or highest is None:
            raise SystemExit("The database holds no timestamps to rebase.")

        target_start = _day_start(target, zone)
        now = datetime.now(timezone.utc)
        span = highest - lowest
        available = now - target_start
        if available <= timedelta(0):
            raise SystemExit("The target day has not started yet in the selected timezone.")
        scale = 1.0 if span <= available else available.total_seconds() / span.total_seconds()
        target_end = target_start + timedelta(seconds=span.total_seconds() * scale)
        rebase = Rebase(origin=lowest, target_start=target_start, scale=scale)

        print(f"Timeline range : {lowest.isoformat()}  ->  {highest.isoformat()}")
        print(f"Target day     : {target.isoformat()} ({arguments.timezone})")
        print(f"Mapped range   : {target_start.isoformat()}  ->  {target_end.isoformat()}")
        print(f"Scale factor   : {scale:.4f}")
        print(f"Tables         : {len({table.name for table, _ in columns})}")

        if arguments.dry_run:
            print("Dry run: nothing was written.")
            return

        backup_root = Path(arguments.backup_dir) if arguments.backup_dir else settings.storage_dir / "backups"
        stamp = datetime.now(zone).strftime("%Y%m%d-%H%M%S")
        backup_dir = backup_root / f"rebase-{target.isoformat()}-{stamp}"
        backup_file = _backup(db, columns, ledger_path, backup_dir)
        print(f"Backup         : {backup_file}")

        # Serialise with concurrent audit appends so the rebuilt chain stays intact.
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 728411903})

        shifted = 0
        existing = set(inspect(db.get_bind()).get_table_names())
        for table, column in columns:
            if table.name not in existing:
                continue
            primary = list(table.primary_key.columns)[0]
            rows = db.execute(select(primary, column)).all()
            payload = []
            for key, value in rows:
                if value is None:
                    continue
                payload.append({"_aq_key": key, "_aq_value": rebase.apply(value)})
            if not payload:
                continue
            statement = (
                update(table)
                .where(primary == bindparam("_aq_key"))
                .values({column.key: bindparam("_aq_value", type_=column.type)})
            )
            db.execute(statement, payload)
            shifted += len(payload)

        audit_entries = _rebuild_audit_chain(db)
        ledger_records, ledger_rows = _rebuild_ledger(db, ledger_path, rebase)

        original_ledger = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else ""
        try:
            _write_ledger(ledger_path, ledger_records)
            db.commit()
        except Exception:
            db.rollback()
            if original_ledger:
                ledger_path.write_text(original_ledger, encoding="utf-8")
            raise

        from app.services.audit import verify_audit_chain

        audit_report = verify_audit_chain(db)
        print(f"Shifted        : {shifted} timestamps")
        print(f"Audit chain    : {'valid' if audit_report['valid'] else 'INVALID'} ({audit_entries} events)")
        print(f"Ledger chain   : {len(ledger_records)} records, {ledger_rows} database rows")
        if not audit_report["valid"]:
            for error in audit_report["errors"][:5]:
                print(f"  ! {error}")


if __name__ == "__main__":
    main()
