"""Provisioning admin API for plugin lifecycle management.

Provides endpoints for installing, listing, and uninstalling plugins in a
workspace.  Authenticated via ``X-Admin-Api-Key`` (``admin_api_only``).
"""

from flask import request
from flask_restx import Resource
from pydantic import BaseModel, Field

from controllers.admin_api import admin_api_ns
from controllers.admin_api.wraps import admin_api_only
from controllers.common.schema import register_schema_models
from controllers.console.wraps import setup_required
from core.plugin.impl.exc import PluginDaemonClientSideError
from graphon.model_runtime.utils.encoders import jsonable_encoder
from services.plugin.plugin_service import PluginService


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class ProvisioningPluginInstallPayload(BaseModel):
    plugin_unique_identifiers: list[str] = Field(description="List of plugin unique identifiers to install")


class ProvisioningPluginInstallGithubPayload(BaseModel):
    plugin_unique_identifier: str = Field(description="Plugin unique identifier")
    repo: str = Field(description="GitHub repository (owner/repo)")
    version: str = Field(description="Version tag or branch")
    package: str = Field(description="Package path within the repo")


class ProvisioningPluginUninstallPayload(BaseModel):
    plugin_installation_id: str = Field(description="Installation ID of the plugin to uninstall")


class ProvisioningPluginListQuery(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=100, ge=1, le=256, description="Page size")


register_schema_models(
    admin_api_ns,
    ProvisioningPluginInstallPayload,
    ProvisioningPluginInstallGithubPayload,
    ProvisioningPluginUninstallPayload,
    ProvisioningPluginListQuery,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/plugins")
class ProvisioningPluginListApi(Resource):
    """List installed plugins in a workspace."""

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_list_plugins")
    @admin_api_ns.doc(description="List installed plugins in a workspace")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningPluginListQuery.__name__])
    def get(self, workspace_id: str):
        args = ProvisioningPluginListQuery.model_validate(request.args.to_dict(flat=True))

        try:
            plugins_with_total = PluginService.list_with_total(workspace_id, args.page, args.page_size)
        except PluginDaemonClientSideError as e:
            return {"code": "plugin_error", "message": e.description}, 400

        return jsonable_encoder({"plugins": plugins_with_total.list, "total": plugins_with_total.total})


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/plugins/install/marketplace")
class ProvisioningPluginInstallMarketplaceApi(Resource):
    """Install plugins from marketplace."""

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_install_plugin_marketplace")
    @admin_api_ns.doc(description="Install plugins from marketplace")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningPluginInstallPayload.__name__])
    def post(self, workspace_id: str):
        args = ProvisioningPluginInstallPayload.model_validate(admin_api_ns.payload or {})

        try:
            response = PluginService.install_from_marketplace_pkg(workspace_id, args.plugin_unique_identifiers)
        except PluginDaemonClientSideError as e:
            return {"code": "plugin_error", "message": e.description}, 400

        return jsonable_encoder(response)


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/plugins/install/github")
class ProvisioningPluginInstallGithubApi(Resource):
    """Install a plugin from GitHub."""

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_install_plugin_github")
    @admin_api_ns.doc(description="Install a plugin from GitHub")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningPluginInstallGithubPayload.__name__])
    def post(self, workspace_id: str):
        args = ProvisioningPluginInstallGithubPayload.model_validate(admin_api_ns.payload or {})

        try:
            response = PluginService.install_from_github(
                workspace_id,
                args.plugin_unique_identifier,
                args.repo,
                args.version,
                args.package,
            )
        except PluginDaemonClientSideError as e:
            return {"code": "plugin_error", "message": e.description}, 400

        return jsonable_encoder(response)


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/plugins/uninstall")
class ProvisioningPluginUninstallApi(Resource):
    """Uninstall a plugin."""

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_uninstall_plugin")
    @admin_api_ns.doc(description="Uninstall a plugin")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningPluginUninstallPayload.__name__])
    def post(self, workspace_id: str):
        args = ProvisioningPluginUninstallPayload.model_validate(admin_api_ns.payload or {})

        try:
            success = PluginService.uninstall(workspace_id, args.plugin_installation_id)
        except PluginDaemonClientSideError as e:
            return {"code": "plugin_error", "message": e.description}, 400

        return {"success": success}
