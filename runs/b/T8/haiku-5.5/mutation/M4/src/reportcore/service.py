"""Service layer. All business rules live here; the store does no authorization."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from .authz import may_read_classification, require_role, require_tenant
from .errors import ReportCoreError, Conflict, Forbidden, NotFound, ValidationError
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


class SavedReportsService:
    """Reference (corrected) SavedReportsService for mutation testing only."""

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
        tenant_id = actor.tenant_id
        report_id = _new_id()
        blob, digest = _canonical(payload)
        with self.store.conn:
            self.store.execute(
                "INSERT INTO reports(id, tenant_id, owner_id, name, classification, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, tenant_id, actor.id, name, classification, _now()),
            )
            self.store.execute(
                "INSERT INTO report_snapshots(report_id, payload_json, content_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (report_id, blob, digest, _now()),
            )
            self.store.add_audit(actor.id, "report.save", "report", report_id, tenant_id, digest)
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
        if snapshot is None:
            raise NotFound("no such object")
        self.store.add_audit(actor.id, "report.read", "report", report_id, row["tenant_id"])
        self.store.commit()
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "owner_id": row["owner_id"],
            "name": row["name"],
            "classification": row["classification"],
            "revoked": row["revoked_at"] is not None,
            "content_hash": snapshot["content_hash"],
            "payload": json.loads(snapshot["payload_json"]),
        }

    def list_reports(self, actor: User) -> list[dict]:
        rows = self.store.fetchall(
            "SELECT id, tenant_id, owner_id, name, classification, revoked_at FROM reports"
            " WHERE tenant_id = ? ORDER BY name",
            (actor.tenant_id,),
        )
        out = [
            {
                "id": r["id"],
                "name": r["name"],
                "classification": r["classification"],
                "owner_id": r["owner_id"],
                "revoked": r["revoked_at"] is not None,
            }
            for r in rows
            if may_read_classification(actor, r["classification"]) and r["revoked_at"] is None
        ]
        self.store.add_audit(actor.id, "report.list", "report", None, actor.tenant_id)
        self.store.commit()
        return out

    def revoke_report(self, actor: User, report_id: str, reason: str = "") -> None:
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        require_role(actor, "admin")
        with self.store.conn:
            self.store.execute(
                "UPDATE reports SET revoked_at = ?, revoked_by = ?, revoke_reason = ?"
                " WHERE id = ?",
                (_now(), actor.id, reason, report_id),
            )
            self.store.add_audit(actor.id, "report.revoke", "report", report_id, row["tenant_id"])

    def save_batch(self, actor: User, items: list) -> dict:
        saved = []
        failed = 0
        for item in items:
            if not isinstance(item, dict):
                failed += 1
                continue
            try:
                saved.append(
                    self.save_report(
                        actor,
                        item.get("name", ""),
                        item.get("payload") or {},
                        item.get("classification", "internal"),
                    )
                )
            except ReportCoreError:
                failed += 1
        status = "complete" if failed == 0 else "partial"
        return {"applied": len(saved), "saved": saved, "status": status}
