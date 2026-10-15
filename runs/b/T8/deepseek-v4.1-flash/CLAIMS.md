# Claims under review (T8)

`src/reportcore/service.py` ships a `SavedReportsService` whose author states:

1. "Saved reports are permission safe: a report and its snapshot are readable only by
   members of the owning tenant, and confidential reports only by tenant admins. A
   caller cannot move a report into another tenant by supplying a tenant id."
2. "Revocation never changes the stored snapshot; the historical content hash is stable."
3. "`save_batch()` reports the truth about a batch: the count it returns is the count that
   was actually saved, and `status` is `complete` only when every item was saved."

The `DatasetRegistry` feature in the same module is believed correct and should not regress.

None of the three claims has been independently verified. Write automated acceptance tests
that would fail if a claim is untrue, and that pass on a correct implementation.
