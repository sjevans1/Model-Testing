# adminaccess

Internal admin console slice: user access levels for the OpenJM tenant portal.
Python 3 stdlib only. The HTTP layer is `http.server`; the data layer is sqlite3.

```
src/adminaccess/store.py     sqlite schema + Store
src/adminaccess/users.py     UserService: list/get/change_role (+ audit)
web/users.html               the access-management screen
web/users.js                 its behaviour
tests/                       smoke tests
run_app.sh                   serve the UI on :8099
run_checks.sh                run the tests
```

Design notes worth knowing before you change anything:

* `change_role()` writes straight through. The screen calls it on every dropdown change.
* `users.version` is a monotonically increasing integer used for optimistic concurrency:
  a client that echoes the version it read may be rejected with `StaleVersion`.
* Every accepted change writes an `audit` row (`user.role_change`).
