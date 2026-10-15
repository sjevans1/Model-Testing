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


class SavedReportsService:
    """Tenant-scoped saved reports with immutable, auditable snapshots."""

    def __init__(self, store: Store) -> None:
        self.store = store

    @staticmethod
    def _canonical_payload(payload: dict) -> tuple[str, str]:
        """Serialize JSON data strictly so the hash describes the stored snapshot."""
        def is_json_value(value: Any) -> bool:
            if value is None or isinstance(value, (str, bool, int)):
                return True
            if isinstance(value, float):
                return value == value and value not in (float("inf"), float("-inf"))
            if isinstance(value, list):
                return all(is_json_value(item) for item in value)
            if isinstance(value, dict):
                return all(isinstance(key, str) and is_json_value(item) for key, item in value.items())
            return False

        try:
            if not is_json_value(payload):
                raise ValidationError("payload must contain only JSON values and string keys")
            blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValidationError("payload must be valid JSON") from exc
        return blob, hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_report_id(report_id: Any) -> str:
        if not isinstance(report_id, str) or not report_id.strip():
            raise ValidationError("report_id must be a non-empty string")
        return report_id

    def save_report(
        self, actor: User, name: str, payload: dict, classification: str = "internal"
    ) -> str:
        name = _validate_name(name)
        payload = _validate_payload(payload)
        classification = _validate_classification(classification)
        blob, digest = self._canonical_payload(payload)
        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")

        report_id = _new_id()
        created_at = _now()
        with self.store.conn:
            self.store.execute(
                "INSERT INTO reports(id, tenant_id, owner_id, name, classification, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, actor.tenant_id, actor.id, name, classification, created_at),
            )
            self.store.execute(
                "INSERT INTO report_snapshots(report_id, payload_json, content_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (report_id, blob, digest, created_at),
            )
            self.store.add_audit(
                actor.id, "report.save", "report", report_id, actor.tenant_id, digest
            )
        return report_id

    def get_report(self, actor: User, report_id: str) -> dict:
        report_id = self._validate_report_id(report_id)
        require_role(actor, "viewer")
        row = self.store.fetchone(
            "SELECT * FROM reports WHERE id = ? AND tenant_id = ?",
            (report_id, actor.tenant_id),
        )
        if row is None:
            raise NotFound("no such object")
        if not may_read_classification(actor, row["classification"]):
            raise Forbidden("classification not readable by this role")
        if row["revoked_at"] is not None:
            raise Conflict("report has been revoked")
        snapshot = self.store.fetchone(
            "SELECT s.* FROM report_snapshots AS s JOIN reports AS r ON r.id = s.report_id"
            " WHERE s.report_id = ? AND r.tenant_id = ?",
            (report_id, actor.tenant_id),
        )
        if snapshot is None:
            # A report without its immutable snapshot is corrupted, not an empty report.
            raise Conflict("report snapshot is unavailable")
        self.store.add_audit(actor.id, "report.read", "report", report_id, actor.tenant_id)
        self.store.commit()
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "owner_id": row["owner_id"],
            "name": row["name"],
            "classification": row["classification"],
            "content_hash": snapshot["content_hash"],
            "payload": json.loads(snapshot["payload_json"]),
        }

    def list_reports(self, actor: User) -> list[dict]:
        require_role(actor, "viewer")
        rows = self.store.fetchall(
            "SELECT id, name, classification, owner_id FROM reports"
            " WHERE tenant_id = ? AND revoked_at IS NULL ORDER BY name, id",
            (actor.tenant_id,),
        )
        visible = [dict(row) for row in rows if may_read_classification(actor, row["classification"])]
        self.store.add_audit(actor.id, "report.list", "report", None, actor.tenant_id)
        self.store.commit()
        return visible

    def revoke_report(self, actor: User, report_id: str, reason: str = "") -> None:
        report_id = self._validate_report_id(report_id)
        if not isinstance(reason, str):
            raise ValidationError("reason must be a string")
        require_role(actor, "analyst")
        row = self.store.fetchone(
            "SELECT id, owner_id, revoked_at FROM reports WHERE id = ? AND tenant_id = ?",
            (report_id, actor.tenant_id),
        )
        if row is None:
            raise NotFound("no such object")
        if actor.id != row["owner_id"] and role_level(actor.role) < role_level("admin"):
            raise Forbidden("only the report owner or an admin may revoke it")
        if row["revoked_at"] is not None:
            raise Conflict("report has already been revoked")

        revoked_at = _now()
        with self.store.conn:
            self.store.execute(
                "UPDATE reports SET revoked_at = ?, revoked_by = ?, revoke_reason = ?"
                " WHERE id = ? AND tenant_id = ? AND revoked_at IS NULL",
                (revoked_at, actor.id, reason, report_id, actor.tenant_id),
            )
            self.store.add_audit(
                actor.id, "report.revoke", "report", report_id, actor.tenant_id, reason
            )
