"""Phase 8C Lambda handlers — one responsibility per function.

Handlers are plain ``handler(event, context) -> dict`` callables that can run
under AWS Lambda or via the local runner. Business logic is delegated to
existing services; this package only adapts events, secrets, and DI.
"""

from app.lambdas.handlers.cleanup import handler as cleanup_handler
from app.lambdas.handlers.collect_metrics import handler as collect_metrics_handler
from app.lambdas.handlers.discover_schema import handler as discover_schema_handler
from app.lambdas.handlers.execute_migration import handler as execute_migration_handler
from app.lambdas.handlers.load_schema import handler as load_schema_handler
from app.lambdas.handlers.persist_results import handler as persist_results_handler
from app.lambdas.handlers.provision_shadow import (
    handler as provision_shadow_cluster_handler,
)

HANDLERS = {
    "discover-schema": discover_schema_handler,
    "provision-shadow-cluster": provision_shadow_cluster_handler,
    "load-schema": load_schema_handler,
    "execute-migration": execute_migration_handler,
    "collect-metrics": collect_metrics_handler,
    "persist-results": persist_results_handler,
    "cleanup": cleanup_handler,
}

__all__ = [
    "HANDLERS",
    "cleanup_handler",
    "collect_metrics_handler",
    "discover_schema_handler",
    "execute_migration_handler",
    "load_schema_handler",
    "persist_results_handler",
    "provision_shadow_cluster_handler",
]
