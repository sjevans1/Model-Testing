# Code review: BENCH-MODEL-001 / T7

## 1. Blocking findings

### B1 — Role requests no longer enforce administrator or role validation; tenant is not bound to the target

- **File/location:** `sources/src/roleservice.py:36-42` (diff removes the checks at old lines 36-37); the request's target user is later mutated at `sources/src/roleservice.py:50-55`.
- **Severity:** Blocker.
- **Why blocking:** `request_role_change` now accepts any actor and any role string, and stores the actor's tenant without checking the target user's tenant. A request can therefore be created by a non-admin for a user in another tenant, using an invalid role. `approve` applies the request's role to the user by ID. This violates the admin-only, valid-role and tenant-boundary requirements.
- **Evidence:** A runtime probe using a `t2` analyst actor called `request_role_change(..., "u1", "superuser")` where `u1` belongs to `t1`; the call returned a request ID. `approve` then changed `u1` to `superuser`. The probe also showed that the request was recorded with tenant `t2` although its target user belongs to `t1`. Source evidence: request insertion uses `actor["tenant_id"]` and does no target lookup/check (`:38-42`); approval updates `users` only by `id` (`:51-54`).
- **Required correction:** Restore authorization and role validation before inserting a request. Resolve the target user and require its `tenant_id` to equal the actor's tenant. Persist/verify the target tenant consistently, and have approval re-check those invariants against the current user and authorized actor before mutation.
- **Residual uncertainty:** The supplied tree contains no outer authorization or tenant-enforcement layer. If one exists outside this service, it is not shown and cannot make the service's direct call paths safe absent a documented, enforced boundary.

### B2 — Approval does not authorize the approver or enforce tenant and pending-state constraints; replay applies the mutation again

- **File/location:** `sources/src/roleservice.py:50-55`.
- **Severity:** Blocker.
- **Why blocking:** `actor` is unused; the method accepts an approval from any role/tenant. It selects a request globally by ID, changes the target globally by user ID, and does not require the request to be pending. Calling it twice repeats the update and increments the user's `version` twice. The same action therefore is not idempotent.
- **Evidence:** The runtime probe called `approve` twice for one request; the user's version advanced from 1 to 3, demonstrating that each replay executes another update. A non-admin actor from `t2` also successfully approved a request targeting a `t1` user in the probe. The code has no actor/tenant/status predicate (`:51-55`).
- **Required correction:** Require an administrator authorized for the request's tenant; verify the target still belongs to that tenant; and perform an atomic pending-to-approved transition that succeeds only once (for example, a conditional update/transaction with a checked affected-row count). Return a defined already-processed/not-found error on repeats.
- **Residual uncertainty:** The service is the only implementation supplied. An upstream guard could restrict who reaches this method, but no such guard is evidenced here; it would not address replay without a one-time state transition.

### B3 — The new direct and bulk mutation methods bypass the required guards

- **File/location:** `sources/src/roleservice.py:61-74`.
- **Severity:** Blocker.
- **Why blocking:** Both new methods ignore `actor`, accept arbitrary role strings, and update users by ID without checking the user's tenant. Either method can thus mutate another tenant's user or assign an invalid role, and non-admins can call them. `apply_bulk` performs this for every supplied entry.
- **Evidence:** In the runtime probe, a non-admin `t2` actor used `change_role_direct` to set the `t1` user's role to `superuser`, then used `apply_bulk` to set the `t2` user's role to `admin`. The SQL at `:62-63` and `:70-71` filters only on user ID; no authorization, tenant lookup, or role validation appears in either method.
- **Required correction:** Enforce admin authorization, allowed-role validation, and actor/target tenant equality for every requested mutation. For bulk operations, validate every item before applying any update and scope each target to the authorized tenant; make failure semantics explicit and report only rows actually changed.
- **Residual uncertainty:** No API/controller layer is included, so it is unknown whether callers also impose checks. The methods themselves are callable without them, and the supplied tests invoke them directly.

### B4 — Role mutations are not audited

- **File/location:** `sources/src/roleservice.py:50-55`, `61-65`, and `67-74`.
- **Severity:** Blocker.
- **Why blocking:** Approval, direct changes, and bulk changes commit role updates without inserting audit records. The only audit insertion in this implementation is for `role.request` (`:43-47`), which does not record whether or how the role was actually changed. This fails the requirement that administrative actions be audited and leaves no mutation record for the new write paths.
- **Evidence:** The runtime probe queried `audit` after request, approval, direct change, and bulk change. It found only the two `role.request` entries; there were no entries for the role mutations. The relevant mutation methods contain no audit insertion before commit.
- **Required correction:** Write an audit event for each successful role mutation, identifying actor, tenant, action, target, and before/after role; commit the audit and role update atomically. Do not emit a successful-mutation audit when no row was changed.
- **Residual uncertainty:** The supplied `audit` table and service are the only audit mechanism shown. An external audit system is not evidenced.

### B5 — Pending-request listing exposes all tenants' requests to any actor

- **File/location:** `sources/src/roleservice.py:57-59`.
- **Severity:** Blocker.
- **Why blocking:** The new method ignores its actor and selects every pending request, with no tenant filter or administrator check. Returned rows include user IDs, tenant IDs, requested roles, and requester IDs, allowing cross-tenant disclosure.
- **Evidence:** In the runtime probe, a `t2` viewer received a pending request for `u1` in `t1`; the returned row contained its target and requested role. The query at `:58` filters only on status.
- **Required correction:** Require an authorized administrator and filter results to that actor's tenant, preferably joining the target user and checking its current tenant. Return only fields callers need.
- **Residual uncertainty:** No separate service/API authorization layer is present in the supplied tree.

## 2. Non-blocking findings

### N1 — Approval of an unknown request now fails with an unhandled indexing error

- **File/location:** `sources/src/roleservice.py:51-53` (the diff removes the prior `row is None` validation).
- **Severity:** Medium.
- **Why non-blocking:** An unknown request ID makes `fetchone()` return `None`, after which the code indexes `row["requested_role"]`; callers receive an incidental runtime exception rather than the service's defined `ValidationError` behavior. This is not the primary authorization flaw but degrades predictable error handling.
- **Evidence:** The diff deletes the explicit `if row is None: raise ValidationError(...)` guard; the new code immediately indexes `row` at line 53.
- **Suggested correction:** Restore explicit not-found handling and return the documented domain error. Include it in the atomic approval path described in B2.
- **Residual uncertainty:** No caller/error-mapping contract is supplied, so the externally visible response is unknown.

### N2 — Tests remove security regression cases and do not exercise the new safeguards

- **File/location:** `sources/tests/test_roleservice.py:24-40`; deleted cases shown at `pr.diff:123-140`.
- **Severity:** Medium.
- **Why non-blocking:** The change removes tests for non-admin requests, invalid roles, and cross-tenant behavior, replacing them with happy-path approval and bulk-result checks. The remaining tests pass while the security violations above remain reachable.
- **Evidence:** `python3 -m unittest discover -s tests -v` (run from `sources/`) reported 3 tests, all passing. The diff shows the deleted security assertions and the replacement tests.
- **Suggested correction:** Restore and retain the relevant regression tests, and add coverage for tenant isolation, authorization, role validation, audit records, and replay for each mutation path.
- **Residual uncertainty:** No broader CI suite or external integration tests were supplied.

## 3. Findings considered and rejected

- **The new `idx_role_requests_status` index (`sources/src/roleservice.py:17`) is a defect:** rejected. It is a plausible performance index for the new pending-status query and does not weaken correctness.
- **Replacing millisecond-derived request IDs with UUID-derived IDs (`sources/src/roleservice.py:37`) is a defect:** rejected. This is a reasonable collision-resistance improvement; the truncated ID's operational collision rate is not established by the supplied evidence, so I am not raising it.
- **The happy-path `approve_applies_the_role` and bulk completion tests establish the required guarantees:** rejected. They establish only basic successful behavior; the runtime probe and implementation show that authorization, tenant isolation, auditing, and replay safety are not tested or enforced.

## 4. Verification and merge recommendation

- `python3 -m unittest discover -s tests -v` (working directory: `sources`) — 3 tests passed.
- Runtime probe command (run from the review directory): `python3 -c 'import sys;sys.path.insert(0,"sources/src");from roleservice import Store,RoleService;s=Store();s.conn.executemany("INSERT INTO users VALUES(?,?,?,?)",[("u1","t1","viewer",1),("u2","t2","viewer",1)]);s.conn.commit();r=RoleService(s);x={"id":"x","tenant_id":"t2","role":"viewer"};rid=r.request_role_change(x,"u1","superuser");print("created",rid);print("t2_list",[(q["user_id"],q["tenant_id"],q["requested_role"]) for q in r.list_pending(x)]);r.approve(x,rid);r.approve(x,rid);print("u1",tuple(s.conn.execute("SELECT tenant_id,role,version FROM users WHERE id=?",("u1",)).fetchone()));r.change_role_direct(x,"u1","superuser");r.apply_bulk(x,[{"user_id":"u2","role":"admin"}]);print("u1_after_direct",tuple(s.conn.execute("SELECT tenant_id,role,version FROM users WHERE id=?",("u1",)).fetchone()));print("u2_after_bulk",tuple(s.conn.execute("SELECT tenant_id,role,version FROM users WHERE id=?",("u2",)).fetchone()));print("audit",[(q["action"],q["object_id"]) for q in s.conn.execute("SELECT action,object_id FROM audit")])'` — output: request created; `t2_list` returned `u1` with `superuser`; repeated approval left `u1` at version 3; direct mutation changed it again; bulk changed `u2` to admin; audit contained only `role.request`.
- **Recommendation: Do not merge.** The request and mutation paths violate the product's tenant, administrator, audit, and replay requirements. Merge only after the blocking findings are corrected and regression tests demonstrate the guarantees on every write path.
