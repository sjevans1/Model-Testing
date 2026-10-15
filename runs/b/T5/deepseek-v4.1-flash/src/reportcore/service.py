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
    """Saved Reports.

    Authorization, as reviewed and corrected:

    * reads are tenant-scoped; a foreign tenant is a ``NotFound`` identical to a
      missing object, never a ``Forbidden``;
    * ``confidential`` reports are readable (and creatable) only by tenant admins;
    * tenant and owner always come from the authenticated actor, never the payload;
    * revocation is tenant-scoped and limited to the owner or a tenant admin;
    * every mutation and every successful report read is audited;
    * an unknown, empty or unrecognised role is denied everywhere (fail closed);
    * ``save_batch`` reports what it actually saved.

    All of that is done with the primitives in :mod:`reportcore.authz`; no second
    authorization layer is introduced here.
    """

    def __init__(self, store: Store) -> None:
        self.store = store

    def save_report(
        self, actor: User, name: str, payload: dict, classification: str = "internal"
    ) -> str:
        name = _validate_name(name)
        payload = _validate_payload(payload)
        classification = _validate_classification(classification)
        # D7 fixed: creating a report is a role-gated mutation (analyst and up), and a
        # classified report requires an admin, exactly like DatasetRegistry.save_dataset.
        require_role(actor, "analyst")
        if classification == "confidential":
            require_role(actor, "admin")
        # D5 fixed: tenant and owner are taken from the authenticated actor. Anything in
        # *payload* is caller-controlled content and never decides ownership.
        tenant_id = actor.tenant_id
        owner_id = actor.id
        report_id = _new_id()
        blob, digest = _canonical(payload)
        with self.store.conn:
            self.store.execute(
                "INSERT INTO reports(id, tenant_id, owner_id, name, classification, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, tenant_id, owner_id, name, classification, _now()),
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
        # D1 fixed: the actor's tenant is checked before anything is read. A foreign
        # report is a NotFound with the same message as a missing one, so the caller
        # cannot tell that the object exists elsewhere.
        require_tenant(actor, row["tenant_id"])
        # D3 fixed: classification is enforced on the read, like DatasetRegistry.get_dataset.
        if not may_read_classification(actor, row["classification"]):
            raise Forbidden("classification not readable by this role")
        snapshot = self.store.fetchone(
            "SELECT * FROM report_snapshots WHERE report_id = ?", (report_id,)
        )
        if snapshot is None:
            raise NotFound("no such object")
        self.store.add_audit(actor.id, "report.read", "report", report_id, actor.tenant_id)
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
        # D6 fixed: only this tenant's rows, only classifications the actor may read, and
        # `revoked` reports the stored state instead of a hard-coded False.
        # D4/D7 fixed: may_read_classification is fail-closed, so an unrecognised role
        # sees nothing at all (same shape as DatasetRegistry.list_datasets).
        out = [
            {
                "id": r["id"],
                "name": r["name"],
                "classification": r["classification"],
                "owner_id": r["owner_id"],
                "revoked": r["revoked_at"] is not None,
            }
            for r in rows
            if may_read_classification(actor, r["classification"])
        ]
        self.store.add_audit(actor.id, "report.list", "report", None, actor.tenant_id)
        self.store.commit()
        return out

    def revoke_report(self, actor: User, report_id: str, reason: str = "") -> None:
        row = self.store.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if row is None:
            raise NotFound("no such object")
        # D2 fixed: same tenant-or-NotFound rule as every other read, then owner-or-admin.
        require_tenant(actor, row["tenant_id"])
        if actor.id == row["owner_id"]:
            # An owner still has to hold a real role: revocation is a mutation, so an
            # unrecognised principal is refused rather than silently ignored.
            require_role(actor, "viewer")
        else:
            require_role(actor, "admin")
        with self.store.conn:
            self.store.execute(
                "UPDATE reports SET revoked_at = ?, revoked_by = ?, revoke_reason = ?"
                " WHERE id = ?",
                (_now(), actor.id, reason, report_id),
            )
            # The snapshot is never touched: revocation only flips the status columns.
            self.store.add_audit(actor.id, "report.revoke", "report", report_id, actor.tenant_id)

    def save_batch(self, actor: User, items: list) -> dict:
        """Save several reports at once and report how the batch actually went."""
        if not isinstance(items, (list, tuple)):
            raise ValidationError("items must be a list")
        saved: list[str] = []
        for item in items:
            try:
                if not isinstance(item, dict):
                    raise ValidationError("batch item must be an object")
                saved.append(
                    self.save_report(
                        actor,
                        item.get("name", ""),
                        item.get("payload") or {},
                        item.get("classification", "internal"),
                    )
                )
            except Exception:  # noqa: BLE001
                # D8 fixed: a per-item failure is expected to be isolated, but it is
                # counted as a failure instead of being reported as a success.
                continue
        return {
            "applied": len(saved),
            "saved": saved,
            "status": "complete" if len(saved) == len(items) else "partial",
        }
