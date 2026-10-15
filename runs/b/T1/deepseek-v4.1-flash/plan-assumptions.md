# plan-assumptions.md — every assumption made in plan.md

Each entry states the assumption, why it was needed (what `FACTS.md` does not settle), and the
impact if it is wrong. Assumptions are numbered `A-n` and are cited from `plan.md`.

Anything **not** listed here is traceable to `FACTS.md` (`F1`–`F18` in `plan.md` §0.2).

---

**A-1 — There is no central secret store today.**
`FACTS.md` says model access is per-provider API keys [F18] and that credential rotation by an
operator must be possible [F15], but describes no secret manager. Assumed: credentials are
currently held in per-service configuration/environment, so a secret store is new work (WP-1).
*If wrong* (a vault already exists): WP-1 shrinks to extension/configuration and the connector
packages get cheaper.

**A-2 — The platform is single-region today; regional placement is new work.**
[F1] describes one multi-tenant SaaS deployment; [F12] requires per-customer-region data. The
two are only reconcilable if regional placement is built. Assumed: no regional sharding exists,
so residency (NFR-PR1, §6.3) is [NEW] and must not be claimed as already satisfied.
*If wrong*: residency tests (§9) become verification of existing topology instead of new build.

**A-3 — Dataset/table classification does not exist and must be added.**
[F6] classifies *documents*; [F14] speaks of *documents*. Structured sources are new, so they
have no classification at all. Assumed: the `internal`/`confidential` vocabulary is extended to
datasets/exposed objects (WP-8), defaulting to most-restrictive until an administrator sets it
(deny-by-default). This is an extension of an existing idea, not a new policy engine [F18].
*If wrong*: the data-gating portion of §5.2/§5.3 is mis-scoped.

**A-4 — LLM provider contracts must be amended to exclude training on submitted content.**
[F12] prohibits cross-tenant training but `FACTS.md` does not state current provider terms.
Assumed: terms must be contractually confirmed/amended before customer content is sent
(NFR-PR2). *If wrong*: the constraint already holds and no action is needed.

**A-5 — The vector index is chosen/self-managed as part of this work.**
[F18] says no vector database exists. Assumed the index is selected and operated by this plan
(WP-10) rather than provided by the platform. *If wrong*: WP-10 reduces to integration.

**A-6 — Specific ERP and warehouse products are unknown.**
The scenario says "ERP databases" and "a data warehouse"; [F18] names SAP/NetSuite/Dynamics and
Snowflake/BigQuery/Redshift as absent but does not say which the customer uses. Assumed:
product-agnostic connector contract first, with the first ERP integration run as a
discovery-bounded project (WP-7). *If wrong*: only WP-6/WP-7 scope shifts, not the framework.

**A-7 — Connectors can reach customer source systems from the tenant's region.**
Neither `FACTS.md` nor the scenario states network topology (VPN, private link, public endpoint).
Assumed reachability is provided by the customer/deployment; the plan does not design network
connectivity. *If wrong*: a connectivity package (tunnelling/private networking) must be added
ahead of WP-3..WP-7.

**A-8 — Proposed SLOs and the availability target.**
[FACTS.md] gives no latency/availability numbers. The figures in §2.1 and NFR-A1 (99.5 %) are
proposals to be ratified. Assumed: they are the acceptance thresholds until the business
overrides them. *If wrong*: only the numbers change; the structure (per-tenant, degradation-
aware) does not.

**A-9 — The permission filter can be pushed into the index/store.**
NFR-P5 assumes the chosen vector index supports metadata filtering (tenant, workspace,
classification) natively. Assumed: it does, so no unbounded post-filter is needed. *If wrong*:
candidate-set sizing and latency targets (§2.1) must be re-derived, or a different index chosen.

**A-10 — Content-hash keyed embeddings.**
Assumed chunk identity is stable enough that unchanged content can be skipped on re-ingest
(NFR-C3). *If wrong*: re-embedding cost rises; dedupe must be redesigned.

**A-11 — A provider/model catalogue is a reasonable new artifact.**
[F18] says there is no managed gateway and access is per-provider keys. Assumed a catalogue of
approved providers/models, selectable per request class, is the right shape for WP-13. *If
wrong*: the gateway still exists but its configuration surface changes.

**A-12 — Log/metric redaction is achievable by rule.**
NFR-PR5 assumes customer content and prompts can be excluded from logs by policy/rule. *If
wrong*: a more invasive logging boundary is needed.

**A-13 — Encryption at rest/in transit for the new stores is required and feasible.**
Assumed standard encryption applies to the new vector index, caches and secret store. *If
wrong*: an explicit crypto requirement package is added.

**A-14 — The existing observability stack is reused.**
[F10] names logs, Prometheus and failed-job alerts. Assumed new metrics/alerts (WP-19) fit that
stack rather than requiring a new product. *If wrong*: an observability platform decision must
precede WP-19.

**A-15 — Incremental extraction by watermark or logical replication.**
Assumed source systems expose a usable change indicator (timestamp/sequence) or replication.
*If wrong*: full-refresh extraction with higher cost/latency is the fallback (NFR-P3).

**A-16 — Reranking stays out of scope for v1.**
[F18] lists no reranking; assumed hybrid retrieval is acceptable without it, and reranking is a
later, gated enhancement that must pass the same filters. *If wrong*: quality targets may force
it sooner, but it does not change the permission model.

**A-17 — Text-to-SQL is deferred and gated.**
Assumed v1 answers data questions through a curated catalogue (WP-12), with free-form SQL as a
later, separately evaluated capability. *If wrong*: the data-governance test set (§9) must be
substantially widened before any release.

**A-18 — The 25 MB document ceiling is kept for v1.**
[F6] sets the ceiling. Assumed it is acceptable for this product's documents; raising it is
separate work. *If wrong*: ingestion limits and NFR-P4 change.

**A-19 — Role semantics for `viewer` vs `analyst`.**
[F3] gives the ordering `viewer < analyst < admin` but not the data privileges of each.
Assumed `viewer` consumes answers over `internal` knowledge only and `analyst` additionally
drives dataset queries (§5.3). *If wrong*: the matrix is corrected, but the enforcement
mechanism is unchanged.

**A-20 — Classification downgrade warrants extra confirmation (possible two-person review).**
[F17] requires access changes to be deliberate/audited/reversible; the exact ceremony is
unstated. Assumed a confirmation step, with two-person review as a candidate for
`confidential → internal`. *If wrong*: the ceremony is lightened or tightened.

**A-21 — Classification changes invalidate derived/cached artifacts.**
Assumed caches and cached answers referencing a reclassified unit must be invalidated with it.
Derives from [F14] + [F17]; the cache layer does not exist yet so it is design, not fact.
*If wrong*: a subtler invalidation scheme is needed.

**A-22 — Confirmation steps for destructive/widening actions.**
Assumed the "deliberate" requirement [F17] implies an explicit confirmation for deletion,
credential rotation, classification downgrade and entitlement increase. *If wrong*: reduce to
audited single action.

**A-23 — Documents can carry adversarial instructions (prompt injection).**
Assumed ingested content is untrusted input and cannot be allowed to change entitlements or
reach other sources (§9 red-team layer: A-23). `FACTS.md` is silent; standard threat modelling
puts it in scope. *If wrong*: the red-team layer is still harmless but lower priority.

**A-24 — Feature flags are scoped by plane and tenant.**
Assumed a flag mechanism granular enough to enable OP/CA/EU surfaces and canary tenants
independently (§10.1). *If wrong*: rollout becomes coarser (all-tenant) and rollback drills
change.

**A-25 — Migrations can be kept additive/backward-compatible.**
Assumed the PostgreSQL schema [F1] can take additive-only migrations per release so the prior
release still runs during rollback (§10.3). *If wrong*: coordinated (downtime) releases may be
required for some schema changes.

---

## Assumptions deliberately **not** made

For the avoidance of doubt, this plan does **not** assume any of the following, because
`FACTS.md` says they do not exist ([F18]) and the plan scopes them as new work instead:

- an existing vector store, embedding pipeline or reranking step;
- an existing ERP, data-warehouse, SQL Server or object-storage connector;
- an existing policy engine beyond Keycloak roles and workspace membership;
- document-level ACLs beyond `internal`/`confidential`;
- a managed LLM gateway;
- an agentic automation or approval-workflow framework.

It also does **not** assume regional deployment (A-2) or dataset-level classification (A-3)
already exist; both are presented as new work.
