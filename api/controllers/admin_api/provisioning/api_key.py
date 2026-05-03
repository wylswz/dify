"""Provisioning admin API for app API key management.

Provides CRUD endpoints for app API keys within a workspace.
Authenticated via ``X-Admin-Api-Key`` (``admin_api_only``).
"""

from flask_restx import Resource
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DataError

from controllers.admin_api import admin_api_ns
from controllers.admin_api.wraps import admin_api_only
from controllers.common.schema import register_schema_models
from controllers.console.wraps import setup_required
from extensions.ext_database import db
from models.enums import ApiTokenType
from models.model import ApiToken, App
from services.api_token_service import ApiTokenCache


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class ProvisioningApiKeyCreatePayload(BaseModel):
    name: str | None = Field(default=None, description="Optional name for the API key")


register_schema_models(admin_api_ns, ProvisioningApiKeyCreatePayload)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/apps/<string:app_id>/api-keys")
class ProvisioningAppApiKeyListApi(Resource):
    """List and create API keys for an app."""

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_list_app_api_keys")
    @admin_api_ns.doc(description="List API keys for an app")
    def get(self, workspace_id: str, app_id: str):
        try:
            app = db.session.get(App, app_id)
        except DataError:
            return {"message": "app not found"}, 404
        if not app or str(app.tenant_id) != workspace_id:
            return {"message": "app not found"}, 404

        keys = db.session.scalars(
            select(ApiToken).where(
                ApiToken.type == ApiTokenType.APP,
                ApiToken.app_id == app_id,
            )
        ).all()

        result = []
        for key in keys:
            result.append(
                {
                    "id": str(key.id),
                    "token": key.token,
                    "last_used_at": key.last_used_at.isoformat() + "Z" if key.last_used_at else None,
                    "created_at": key.created_at.isoformat() + "Z" if key.created_at else None,
                }
            )
        return {"data": result}

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_create_app_api_key")
    @admin_api_ns.doc(description="Create a new API key for an app")
    def post(self, workspace_id: str, app_id: str):
        try:
            app = db.session.get(App, app_id)
        except DataError:
            return {"message": "app not found"}, 404
        if not app or str(app.tenant_id) != workspace_id:
            return {"message": "app not found"}, 404

        # Check key limit
        current_count = db.session.scalar(
            select(func.count(ApiToken.id)).where(
                ApiToken.type == ApiTokenType.APP,
                ApiToken.app_id == app_id,
            )
        ) or 0

        if current_count >= 10:
            return {"message": "Cannot create more than 10 API keys for this app"}, 400

        key = ApiToken.generate_api_key("app-", 24)
        api_token = ApiToken()
        api_token.app_id = app_id
        api_token.tenant_id = workspace_id
        api_token.token = key
        api_token.type = ApiTokenType.APP
        db.session.add(api_token)
        db.session.commit()

        return {
            "id": str(api_token.id),
            "token": api_token.token,
            "created_at": api_token.created_at.isoformat() + "Z" if api_token.created_at else None,
        }, 201


@admin_api_ns.route(
    "/provisioning/workspaces/<string:workspace_id>/apps/<string:app_id>/api-keys/<string:api_key_id>"
)
class ProvisioningAppApiKeyApi(Resource):
    """Delete an API key for an app."""

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_delete_app_api_key")
    @admin_api_ns.doc(description="Delete an API key for an app")
    def delete(self, workspace_id: str, app_id: str, api_key_id: str):
        try:
            app = db.session.get(App, app_id)
        except DataError:
            return {"message": "app not found"}, 404
        if not app or str(app.tenant_id) != workspace_id:
            return {"message": "app not found"}, 404

        key = db.session.scalar(
            select(ApiToken)
            .where(
                ApiToken.app_id == app_id,
                ApiToken.type == ApiTokenType.APP,
                ApiToken.id == api_key_id,
            )
            .limit(1)
        )

        if key is None:
            return {"message": "API key not found"}, 404

        ApiTokenCache.delete(key.token, key.type)
        db.session.execute(delete(ApiToken).where(ApiToken.id == api_key_id))
        db.session.commit()

        return {"result": "success"}, 204
