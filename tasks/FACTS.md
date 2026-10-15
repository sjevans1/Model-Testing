# FACTS.md — what exists today, and what is contractually required

Authoritative for T1. If a plan needs something outside this list, it must say so explicitly
instead of assuming it exists.

## Deployed and working (production)

- Multi-tenant SaaS on Ubuntu 24.04, PostgreSQL 16.15, Keycloak 26.7.4 for SSO, Node 22 and
  Python 3.11 services, deployed as a non-root `openjm` user.
- Every request carries a tenant claim; row-level tenant scoping is enforced in application
  code and covered by tests. Customer data for one tenant is never visible to another.
- Keycloak realms per tenant, OIDC with PKCE, group-to-role mapping: roles are
  `viewer` < `analyst` < `admin`, plus platform-operator roles that customers never see.
- An audit table records actor, tenant, action, object and detail for every write and every
  privileged read; audit rows are append-only.
- Workspaces: a named container that groups a customer's folders and resources. Workspace
  membership is the coarse authorization unit today.
- Document ingestion for PDF/DOCX up to 25 MB into object storage, with text extraction and
  a per-document classification of `internal` or `confidential`. Chunking and embeddings are
  **not** in production.
- A retrieval service that searches **whole documents** with PostgreSQL full-text search,
  filtered by workspace membership; there is no vector store in production.
- Connectors: a REST source connector for JSON APIs. No ERP, warehouse, SQL Server or
  object-storage connectors exist yet.
- Operational monitoring: structured logs, Prometheus metrics for request latency and error
  rates, and an alert on failed background jobs.
- CI: GitHub Actions with build, unit and integration tests, a container build and a signed
  release; every merge requires review and green checks.

## Contractual and business requirements

- Customer data stays within the customer's region; no cross-tenant training, no cross-tenant
  retrieval. A tenant administrator can request a data export; a deletion request must remove
  content and embeddings within 30 days.
- Every answer that a user can act on must be traceable to the sources it used, and answers
  that the system is not confident about must say so rather than guess.
- Confidential documents are readable only by tenant administrators, never by `viewer` or
  `analyst`, regardless of workspace membership.
- The operator plane must be able to suspend a tenant, rotate a connector credential and see
  per-tenant usage without being able to read customer content.
- Customer administrators manage their own users, groups and data sources, and cannot see or
  change anything belonging to another customer.
- Administrative changes to access must be deliberate, audited, and reversible.

## Explicitly not available

- No vector database, no embedding pipeline, no reranking in production.
- No ERP (SAP/NetSuite/Dynamics), data-warehouse (Snowflake/BigQuery/Redshift), SQL Server or
  object-storage connector.
- No policy engine beyond Keycloak roles and workspace membership; no document-level ACLs
  beyond the `internal`/`confidential` classification.
- No managed LLM gateway: model access is per-provider API keys today.
- No agentic automation in the product; there is no approval workflow framework to reuse.
