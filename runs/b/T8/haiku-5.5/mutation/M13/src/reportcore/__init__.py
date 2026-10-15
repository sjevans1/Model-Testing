"""reportcore: multi-tenant knowledge/report backend."""
from .authz import may_read_classification, require_role, require_tenant
from .errors import Conflict, Forbidden, NotFound, ReportCoreError, ValidationError
from .models import CLASSIFICATIONS, ROLE_LEVEL, ROLES, Tenant, User, role_level
from .service import DatasetRegistry, SavedReportsService
from .store import Store

__all__ = [
    "CLASSIFICATIONS", "ROLE_LEVEL", "ROLES", "Conflict", "DatasetRegistry", "Forbidden",
    "NotFound", "ReportCoreError", "SavedReportsService", "Store", "Tenant", "User",
    "ValidationError", "may_read_classification", "require_role", "require_tenant", "role_level",
]
