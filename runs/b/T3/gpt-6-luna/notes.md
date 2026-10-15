Saved Reports design and verification

Design decisions

- Saved report metadata and its snapshot are inserted together in one SQLite transaction. The snapshot stores compact, key-sorted JSON and the SHA-256 digest of those exact UTF-8 bytes. Payloads must be JSON values with string object keys; invalid values, non-finite floats, and unsupported Python objects are rejected with ValidationError rather than being stringified.
- Tenant and owner are always taken from the authenticated User. Payload fields with names such as tenant_id or owner_id remain ordinary payload data and cannot change authorization or row ownership.
- Saves require analyst role; confidential saves require admin. Reads and listings require viewer role, and confidential reports are admin-only. Queries that access report data are tenant-scoped; a report in another tenant returns NotFound.
- Listing returns active reports visible to the actor. A revoked report remains stored but is excluded from listings; direct retrieval and repeat revocation raise Conflict. The owner or a same-tenant admin may revoke. Revocation records actor, timestamp, reason, and audit data without updating or deleting the snapshot.
- Successful save, read, list, and revoke operations are audited. Failed authorization and validation attempts do not create audit rows.

Verification

Run from this directory:

    sh run_checks.sh

The first full run after implementation did not pass: one test expected a read audit even though it had not performed a read. The test was corrected to perform the read, and the next full run passed: 7 tests, including the unchanged smoke tests. The suite covers canonical hash/snapshot behavior, actor ownership, tenant isolation, classification/role access, revocation immutability, audit actions, and validation errors.
