"""Service layer. All business rules live here; the store does no authorization."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from .authz import may_read_classification, require_role, require_tenant
from .errors import Conflict, Forbidden, NotFound, ValidationError
from .models import CLASSIFICATIONS, User, role_level
from .store import Store


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return uuid.uuid4().hex


def _canonical(payload: dict) -> tuple[str, str]:
    """Canonical JSON + content hash. Two equal payloads always hash equal."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return blob, hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("name must be a non-empty string")
    return name.strip()


def _validate_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("payload must be an object")
    return payload


def _validate_classification(classification: Any) -> str:
    if classification not in CLASSIFICATIONS:
        raise ValidationError(f"classification must be one of {CLASSIFICATIONS}")
    return classification


class DatasetRegistry:
    """Reference feature: immutable versions, tenant scope, role gate, audit.

    The SavedReportsService below follows exactly these conventions.
    """

    def __init__(self, store: Store) -> None:
        self.store = store

    def save_dataset(
        self, actor: User, name: str, payload: dict, classification: str = "internal"
    ) -> str:
        name = _validate_name(name)
        payload = _validate_payload(payload)
        classification = _validate_classification(classification)
        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")

        dataset_id = _new_id()
        blob, digest = _canonical(payload)
        with self.store.conn:
            self.store.execute(
                "INSERT INTO datasets(id, tenant_id, owner_id, name, classification, created_at,"
                " current_version) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (dataset_id, actor.tenant_id, actor.id, name, classification, _now()),
            )
            self.store.execute(
                "INSERT INTO dataset_versions(dataset_id, version, payload_json, content_hash,"
                " created_at) VALUES (?, 1, ?, ?, ?)",
                (dataset_id, blob, digest, _now()),
            )
            self.store.add_audit(actor.id, "dataset.save", "dataset", dataset_id, actor.tenant_id, digest)
        return dataset_id

    def get_dataset(self, actor: User, dataset_id: str) -> dict:
        row = self.store.fetchone("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        if row is None:
            raise NotFound("no such object")
        require_tenant(actor, row["tenant_id"])
        if not may_read_classification(actor, row["classification"]):
            raise Forbidden("classification not readable by this role")
        version = self.store.fetchone(
            "SELECT * FROM dataset_versions WHERE dataset_id = ? ORDER BY version DESC LIMIT 1",
            (dataset_id,),
        )
        self.store.add_audit(actor.id, "dataset.read", "dataset", dataset_id, actor.tenant_id)
        self.store.commit()
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "owner_id": row["owner_id"],
            "name": row["name"],
            "classification": row["classification"],
            "version": version["version"],
            "content_hash": version["content_hash"],
            "payload": json.loads(version["payload_json"]),
        }

    def list_datasets(self, actor: User) -> list[dict]:
        rows = self.store.fetchall(
            "SELECT id, name, classification, owner_id FROM datasets WHERE tenant_id = ?"
            " ORDER BY name",
            (actor.tenant_id,),
        )
        visible = [dict(r) for r in rows if may_read_classification(actor, r["classification"])]
        self.store.add_audit(actor.id, "dataset.list", "dataset", None, actor.tenant_id)
        self.store.commit()
        return visible


def _status(row: Any) -> str:
    """Derived status. Revocation is a fact recorded on the row, never a deletion."""
    return "revoked" if row["revoked_at"] is not None else "active"


class SavedReportsService:
    """Saved Reports: immutable snapshots, tenant scope, role gate, audit.

    Follows the conventions demonstrated by DatasetRegistry:

    * input is validated before the store is touched;
    * writes are gated with ``require_role(actor, "analyst")`` (confidential content
      additionally needs ``admin``, exactly as ``save_dataset`` does);
    * every query is scoped by ``actor.tenant_id``, and a foreign tenant is a
      ``NotFound`` rather than a ``Forbidden`` so errors never disclose existence;
    * the payload becomes an immutable snapshot: canonical JSON plus a sha256 digest,
      written once in the same transaction as the report row;
    * tenant and owner are taken from the authenticated ``actor`` only -- keys such as
      ``tenant_id``/``owner_id`` inside the caller-controlled payload are ignored;
    * one audit row is written per mutation and per privileged read.

    Revocation flips ``revoked_at``/``revoked_by``/``revoke_reason`` on the report row
    and never touches ``report_snapshots``.
    """

    def __init__(self, store: Store) -> None:
        self.store = store

    def save_report(
        self, actor: User, name: str, payload: dict, classification: str = "internal"
    ) -> str:
        name = _validate_name(name)
        payload = _validate_payload(payload)
        classification = _validate_classification(classification)
        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")

        report_id = _new_id()
        blob, digest = _canonical(payload)
        with self.store.conn:
            self.store.execute(
                "INSERT INTO reports(id, tenant_id, owner_id, name, classification, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, actor.tenant_id, actor.id, name, classification, _now()),
            )
            self.store.execute(
                "INSERT INTO report_snapshots(report_id, payload_json, content_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (report_id, blob, digest, _now()),
            )
            self.store.add_audit(
                actor.id, "report.save", "report", report_id, actor.tenant_id, digest
            )
        return report_id

    def get_report(self, actor: User, report_id: str) -> dict:
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        require_tenant(actor, row["tenant_id"])
        if not may_read_classification(actor, row["classification"]):
            raise Forbidden("classification not readable by this role")
        snapshot = self.store.fetchone(
            "SELECT * FROM report_snapshots WHERE report_id = ?", (report_id,)
        )
        if snapshot is None:  # defensive: the snapshot is written with the report row
            raise NotFound("no such object")
        self.store.add_audit(actor.id, "report.read", "report", report_id, actor.tenant_id)
        self.store.commit()
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "owner_id": row["owner_id"],
            "name": row["name"],
            "classification": row["classification"],
            "created_at": row["created_at"],
            "content_hash": snapshot["content_hash"],
            "payload": json.loads(snapshot["payload_json"]),
            "status": _status(row),
            "revoked_at": row["revoked_at"],
            "revoked_by": row["revoked_by"],
            "revoke_reason": row["revoke_reason"],
        }

    def list_reports(self, actor: User) -> list[dict]:
        rows = self.store.fetchall(
            "SELECT id, tenant_id, owner_id, name, classification, created_at, revoked_at"
            " FROM reports WHERE tenant_id = ? ORDER BY name, id",
            (actor.tenant_id,),
        )
        visible = [
            {**dict(r), "status": _status(r)}
            for r in rows
            if may_read_classification(actor, r["classification"])
        ]
        self.store.add_audit(actor.id, "report.list", "report", None, actor.tenant_id)
        self.store.commit()
        return visible

    def revoke_report(self, actor: User, report_id: str, reason: str = "") -> None:
        if not isinstance(reason, str):
            raise ValidationError("reason must be a string")
        require_role(actor, "analyst")
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        require_tenant(actor, row["tenant_id"])
        if row["revoked_at"] is not None:
            raise Conflict("report is already revoked")
        with self.store.conn:
            self.store.execute(
                "UPDATE reports SET revoked_at = ?, revoked_by = ?, revoke_reason = ?"
                " WHERE id = ?",
                (_now(), actor.id, reason, report_id),
            )
            self.store.add_audit(
                actor.id,
                "report.revoke",
                "report",
                report_id,
                actor.tenant_id,
                reason or None,
            )
        return None
