"""Exception types. Cross-tenant access must be indistinguishable from a missing object."""
from __future__ import annotations


class ReportCoreError(Exception):
    """Base class for every error this package raises."""


class NotFound(ReportCoreError):
    """No such object *visible to this actor* (also used for cross-tenant access)."""


class Forbidden(ReportCoreError):
    """The actor may see the object but is not allowed to perform the action."""


class ValidationError(ReportCoreError):
    """The request itself is malformed."""


class Conflict(ReportCoreError):
    """The request conflicts with current state (e.g. optimistic-concurrency mismatch)."""
