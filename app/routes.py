"""
Flask routes for document migration workflow.

This barrel module re-exports the shared Blueprint and triggers
route registration by importing all sub-modules.
"""

# The Blueprint and shared helpers live in blueprint.py
from app.blueprint import migrate_bp  # noqa: F401  - re-exported for server.py

# Import route modules to register their @migrate_bp.route() decorators
import app.routes_settings   # noqa: F401
import app.routes_batch      # noqa: F401
import app.routes_execute    # noqa: F401
import app.routes_records    # noqa: F401
import app.routes_mapping    # noqa: F401
import app.routes_dms        # noqa: F401
import app.routes_validate   # noqa: F401