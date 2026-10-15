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
        require_tenant(actor, row["tenant_id"])
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
