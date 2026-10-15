# Assumptions for plan.md

Each assumption is referenced as A-n in plan.md. Items not listed here are either stated in FACTS.md or tagged NEW in plan.md.

- A-1: No write-back to ERP or warehouse systems is required; the product is read-only over sources.
- A-2: Region choice (which regions, one cluster or many) is not decided. Plan assumes region-pinned deployments and an LLM/embedding provider that can process data in-region with no-training terms. Provider availability per region is unverified.
- A-3: Group-to-workspace mapping can be implemented via Keycloak group attributes or an application table; the plan does not assume an existing mapping.
- A-4: Connector priority is not specified. Plan assumes PostgreSQL or SQL Server first, object storage second, then one ERP and one warehouse, each chosen by the customer's need.
- A-5: Latency targets (proposed 4 s end-to-end p95, 500 ms retrieval p95) are placeholders, not contractual.
- A-6: Availability target (proposed 99.5% monthly for query path) is a placeholder.
- A-7: Whether structured data is queried at source (federation) or synced to a tenant store is undecided; plan recommends federation first.
- A-8: pgvector inside the existing PostgreSQL 16 is assumed to be acceptable for volume and to meet region and operations needs. Not measured.
- A-9: Reranking is optional and added only if measured recall requires it.
- A-10: The retrieval-score threshold for "insufficient sources" is undefined and must be tuned on the golden set.
- A-11: Column-level classification for structured data is optional; not required by FACTS.md.
- A-12: Audit detail excludes query text by default; customer opt-in for storing it is assumed acceptable.
- A-13: A two-step confirmation for human-gated access changes is needed. FACTS.md says no approval framework exists; the plan assumes a minimal one is acceptable scope.
- A-14: An owner and pass threshold for answer quality evaluation are not defined.
- A-15: LLM and embedding providers will contractually disable training on customer data. Not verified.
- A-16: The existing audit table already enforces append-only at the DB grant level or can be extended to do so. Not verified against code.
- A-17: The existing REST connector can be refactored to the common connector interface without a rewrite. Not verified against code.
- A-18: Existing Keycloak per-tenant realms can carry the roles needed for classification enforcement without a new identity provider.
- A-19: Pilot tenant, region and golden question set are available to the team. Not confirmed.
- A-20: Deletion "content and embeddings within 30 days" includes backups only on a stated backup-expiry policy; backup handling is not specified in FACTS.md and must be decided.
- A-21: Export format is not specified; plan assumes a per-tenant archive of documents plus structured metadata.
- A-22: Work package sizes (small/medium/large) are relative estimates, not measured effort.
