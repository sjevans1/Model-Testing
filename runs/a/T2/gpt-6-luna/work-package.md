# Work package: confirmed, concurrency-safe role changes

## Objective and scope

Change role editing from “dropdown selection writes immediately” to “selection stages a per-user draft; an explicit Save applies it.” A cancelled or failed change must not be reported as applied. Keep the existing roles, tenant-scoped user list, role endpoint, response envelope, SQLite schema, and audit action. Do not redesign the console or add dependencies.

## Files and boundaries

1. `web/users.js`
   - Own the per-row UI state and interaction: persisted role/version, staged role, Save, and Cancel.
   - Consume the existing list response shape `{ "users": [...] }` and preserve the existing role endpoint and `{ "user": ... }` success shape. The current client iterates the list response as an array even though the handler wraps it in an object; correct this narrow integration mismatch as part of wiring the screen.
   - Send the staged role and the version read for that user on Save. A dropdown change must never call the mutation endpoint.
   - Keep the draft after a failed save and show a useful error; update persisted role/version only from a successful server response.

2. `web/users.html`
   - Add an action column if needed for per-row Save and Cancel controls; retain the existing users table and live status region. Controls can be created by `users.js`, so no other markup redesign is needed.

3. `src/adminaccess/users.py`
   - Enforce the mutation authorization rule in `UserService.change_role`, the shared service boundary: only an `Actor` whose role is `admin` may change a role, and the target must remain in that actor's tenant. Do not rely on the UI to hide controls.
   - Apply a version-checked compare-and-swap for version-aware mutations. The role update must include the expected version in its SQL predicate; a pre-read comparison alone is racy. A stale write raises the existing `StaleVersion` error and changes neither role nor version.
   - Validate the requested role against existing `ROLES`. Do not add roles or change role ordering.
   - Define the HTTP mutation contract to require `version`; keep the existing optional service argument only if needed to preserve direct legacy/internal callers, but the HTTP route must reject a missing version rather than silently applying an unguarded request.

4. `src/adminaccess/app.py`
   - Keep `POST /api/users/{id}/role` and the existing success envelope. Map errors explicitly: validation/missing version to 400, unauthenticated/unauthorized mutation to 403 (or 401 only if the existing identity layer distinguishes unauthenticated actors), not found to 404, and stale version to 409 with a machine-readable `StaleVersion` error. Avoid catching every service error and returning 400.
   - Obtain the actor from trusted server-side authentication/context, never from request JSON or a client-controlled role. This slice currently has a module-level demo `ACTOR`; preserve it only as the existing local/demo identity unless an authenticated principal is already provided by the application. Do not invent a new authentication system in this package. If no trusted identity exists in the deployed integration, the route cannot safely authorize mutations and must not be exposed as an authenticated production endpoint until identity wiring is provided.

5. `src/adminaccess/store.py`
   - Use the existing `users.version` and `audit` schema; no schema migration is expected. Provide/use a transaction path so the conditional role update, version increment, and audit insert commit together or roll back together. Ensure the audit helper used in that transaction does not commit partway through it. Preserve existing store helpers used by other callers.

## State and interaction contract

For each user row, hold `persistedRole` and `persistedVersion` from the latest server response, plus `stagedRole` (initially equal to `persistedRole`).

- Current -> staged: changing the dropdown changes only `stagedRole`. It sends no request and writes no audit record. Save is enabled only when staged differs from current and no save is in flight. Cancel restores the dropdown to the persisted role and clears the draft; it sends no request.
- Staged -> applied: Save sends `{ "role": stagedRole, "version": persistedVersion }`. On success, set both persisted role and version from the returned `user`, clear the draft, disable Save, and announce success. A same-as-current save is a no-op: do not send a request, increment version, or audit.
- Failure: do not change the persisted role/version locally and do not announce success. Keep the staged choice visible so it is not silently lost; allow Cancel. Show the error and keep Save available only where retry is safe.
- Stale failure (409): retain the draft but do not automatically retry it with a newer version. Tell the administrator the user changed elsewhere; provide an explicit refresh/reload path to fetch the current role/version and require the administrator to review and stage/confirm again. This prevents a stale confirmation from being silently applied to a new state.
- Disable that row's Save while its request is in flight to prevent duplicate submissions; do not block unrelated rows.

## Authorization and audit

The service, not the browser, is the authorization boundary because callers can invoke the HTTP API directly or alter client code. For every role mutation, require a trusted actor with the `admin` role and enforce same-tenant target scope server-side. Never accept actor ID, tenant, or role from mutation payload. Existing list/get tenant filtering is not a substitute for authorization of a write.

Each successfully applied role change writes exactly one `user.role_change` audit row, in the same transaction as the role/version update. It must identify actor, tenant, target user, timestamp, and old/new roles (the existing `old->new` detail is adequate if retained). Drafts, cancels, rejected/stale requests, and failed transactions write no audit row. A no-op does not count as an applied change and writes no audit row.

## Regression tests to add

Add service tests in `tests/test_smoke.py` (or a focused `tests/test_users.py`, without removing or weakening the existing tests):

- `test_change_role_requires_admin`: non-admin actor receives `Forbidden`; role, version, and audit row count stay unchanged.
- `test_change_role_rejects_cross_tenant_target`: other-tenant target is not mutated and is not audited.
- `test_change_role_persists_increments_version_and_audits_once`: valid admin + matching version changes role, increments version once, and creates one audit row with actor/tenant/object/action and old/new detail.
- `test_change_role_rejects_stale_version_without_side_effects`: save once, then submit the old version; second call raises `StaleVersion`, leaving the first role/version intact and audit count at one.
- `test_change_role_update_and_audit_are_atomic`: force the audit insert to fail; verify role and version roll back and no partial audit is committed.
- `test_change_role_rejects_invalid_role_without_side_effects`: invalid role leaves role/version/audit unchanged.

Add handler tests in `tests/test_app.py` using the standard library HTTP server/test client pattern:

- `test_post_role_requires_version` returns 400 and has no write/audit side effect.
- `test_post_role_success_returns_user_envelope` passes role and version and returns `{ "user": ... }` including the incremented version.
- `test_post_role_stale_version_returns_409` returns an error named `StaleVersion` and makes no second write/audit.
- `test_post_role_non_admin_returns_403` proves authorization is enforced through the API, not only in the UI.
- `test_post_role_not_found_returns_404` preserves the existing not-found boundary.

Add UI regression cases to the available browser test harness (or record them as repeatable browser checks if this repository still has no UI harness):

- `test_role_change_is_staged_until_save`: changing a select sends zero POSTs and leaves the server row unchanged; Save sends exactly one POST with the staged role and displayed version.
- `test_cancel_discards_staged_role`: select a different role, Cancel, verify the original value is restored and no POST occurred.
- `test_failed_save_keeps_draft_and_does_not_claim_success`: simulated non-2xx leaves the draft visible and reports failure.
- `test_stale_save_requires_review_before_retry`: simulated 409 does not auto-retry or overwrite the draft; refresh obtains the latest role/version and the user must make a fresh confirmation.
- `test_success_updates_version_for_next_save`: successful response updates the row's version and the next Save sends that version.

The current repository has no UI test harness; do not add a package dependency solely for these cases. Keep the UI cases as explicit browser checks until an existing harness is available.

## Migration and compatibility risks

- Existing HTTP callers that omit `version` will be rejected once the route requires it. Update the shipped browser client in the same change; identify any external callers before rollout. Do not silently accept missing versions on the HTTP mutation path, since that would bypass stale-write protection.
- Callers that do send a version may now receive 409 instead of the current generic 400 on conflicts; clients must handle that response and must not blindly retry.
- Non-admin callers that previously succeeded due to missing service authorization will now receive 403. This is intentional; confirm intended operator roles before rollout.
- Existing `users` and `audit` columns already support versioning and the required audit data, so do not add a schema migration unless implementation proves a required field is unavailable. Keep the `user.role_change` action and existing list/success response envelopes.
- The list endpoint currently returns `{ "users": [...] }` while the JavaScript currently treats its result as an array. The client must align with the shipped envelope; do not change the endpoint into a bare array as an incidental “fix.”
- `app.py` currently installs a hard-coded demo actor and has no authentication middleware in this slice. Do not mistake that fixture for deployable authorization. The production caller must supply a trusted `Actor`; if there is no such integration, block production exposure rather than trusting a browser-supplied identity.

## Acceptance conditions

1. Selecting a different role causes no network mutation and no database/audit change.
2. Save applies only the staged value, sending the row's current version; success updates displayed persisted state/version and creates one audit record.
3. Cancel restores the persisted value and creates no request/audit record.
4. A failed save is not shown as success; the saved state/version remain unchanged and the staged choice remains recoverable.
5. A stale version returns 409, produces no mutation/audit, and is not automatically retried; the user must refresh/review before a new confirmation.
6. Server rejects unauthorized and cross-tenant role changes even when requests bypass the browser UI.
7. Update plus audit are atomic; invalid, unauthorized, not-found, stale, no-op, or failed operations do not create a role-change audit row.
8. Existing checks still pass, and the added service, handler, and UI regression cases above pass. The list response and role mutation success envelopes remain unchanged.

## Explicitly unchanged

- Available roles and their semantics/order: `viewer`, `analyst`, `admin`.
- Tenant-scoped user listing and target scoping.
- Route path and method: `POST /api/users/{id}/role`.
- Success response envelope `{ "user": row }` and list response envelope `{ "users": [...] }`.
- SQLite `users` and `audit` schema unless a demonstrated need requires otherwise; current per-user integer versioning remains monotonic.
- Audit action name `user.role_change` and the expectation that each accepted change is audited.
- The rest of the admin console, styling, roles, user creation/deletion, and authentication architecture. No broad UI redesign, new framework, dependency, schema migration, or unrelated endpoint changes.
- Existing tests/checks: do not delete, skip, weaken, or retarget them.

## Stop conditions

Stop implementation when all acceptance conditions pass and the named regression cases are covered. Do not proceed into a broad authentication redesign, role-model redesign, audit schema redesign, or unrelated cleanup. If trusted actor identity is unavailable outside the demo fixture, stop before enabling production writes and report that prerequisite rather than weakening server authorization.