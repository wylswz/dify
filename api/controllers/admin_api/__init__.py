"""Admin API for programmatic provisioning of Dify resources.

Exposes provisioning endpoints (apps, plugins, model provider credentials,
API keys) under ``/admin/api``.  Authentication is via ``X-Admin-Api-Key``
header checked against the ``ADMIN_API_KEY`` configuration value.

Unlike the inner API (which is gated behind the ``INNER_API`` feature flag
and never exposed through nginx), the admin API is designed to be reachable
from external automation tools (Terraform, CI/CD, etc.).
"""

from flask import Blueprint
from flask_restx import Namespace

from libs.external_api import ExternalApi

bp = Blueprint("admin_api", __name__, url_prefix="/admin/api")

api = ExternalApi(
    bp,
    version="1.0",
    title="Admin API",
    description="Admin APIs for programmatic provisioning of Dify resources",
)

# Create namespace
admin_api_ns = Namespace("admin_api", description="Admin API provisioning operations", path="/")

from .provisioning import api_key as _prov_api_key
from .provisioning import app as _prov_app
from .provisioning import model_provider as _prov_model_provider
from .provisioning import plugin as _prov_plugin
from .provisioning import tool_provider as _prov_tool_provider

api.add_namespace(admin_api_ns)

__all__ = [
    "_prov_api_key",
    "_prov_app",
    "_prov_model_provider",
    "_prov_plugin",
    "_prov_tool_provider",
    "api",
    "bp",
    "admin_api_ns",
]
