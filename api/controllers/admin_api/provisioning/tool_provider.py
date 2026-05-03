"""Provisioning admin API for builtin tool provider credential management.

Provides CRUD endpoints for builtin tool provider credentials within a workspace.
Authenticated via ``X-Admin-Api-Key`` (``admin_api_only``).
"""

from typing import Any

from flask_restx import Resource
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from controllers.admin_api import admin_api_ns
from controllers.admin_api.wraps import admin_api_only
from controllers.common.schema import register_schema_models
from controllers.console.wraps import setup_required
from core.plugin.entities.plugin_daemon import CredentialType
from extensions.ext_database import db
from graphon.model_runtime.utils.encoders import jsonable_encoder
from libs.helper import uuid_value
from models import Account
from models.account import AccountStatus, TenantAccountJoin, TenantAccountRole
from services.tools.builtin_tools_manage_service import BuiltinToolManageService


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class ProvisioningToolCredentialCreatePayload(BaseModel):
    credentials: dict[str, Any] = Field(description="Provider credentials key-value map")
    name: str | None = Field(default=None, description="Credential name", max_length=30)
    credential_type: str = Field(default="api-key", description="Credential type (api-key, oauth2, unauthorized)")

    @field_validator("credential_type")
    @classmethod
    def validate_credential_type(cls, value: str) -> str:
        try:
            CredentialType(value)
        except ValueError:
            raise ValueError(f"invalid credential_type: {value}")
        return value


class ProvisioningToolCredentialUpdatePayload(BaseModel):
    credential_id: str = Field(description="ID of the credential to update")
    credentials: dict[str, Any] = Field(description="Updated credentials key-value map")
    name: str | None = Field(default=None, description="Credential name", max_length=30)

    @field_validator("credential_id")
    @classmethod
    def validate_credential_id(cls, value: str) -> str:
        return uuid_value(value)


class ProvisioningToolCredentialDeletePayload(BaseModel):
    credential_id: str = Field(description="ID of the credential to delete")

    @field_validator("credential_id")
    @classmethod
    def validate_credential_id(cls, value: str) -> str:
        return uuid_value(value)


register_schema_models(
    admin_api_ns,
    ProvisioningToolCredentialCreatePayload,
    ProvisioningToolCredentialUpdatePayload,
    ProvisioningToolCredentialDeletePayload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_system_account(workspace_id: str) -> Account:
    """Return the first active owner/admin account in the workspace."""
    stmt = (
        select(Account)
        .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
        .where(
            TenantAccountJoin.tenant_id == workspace_id,
            Account.status == AccountStatus.ACTIVE,
            TenantAccountJoin.role.in_([TenantAccountRole.OWNER, TenantAccountRole.ADMIN]),
        )
        .order_by(TenantAccountJoin.created_at.asc())
        .limit(1)
    )
    account = db.session.scalar(stmt)
    if account is not None:
        account.set_tenant_id(workspace_id)
        return account

    # Fallback: any active member
    stmt = (
        select(Account)
        .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
        .where(
            TenantAccountJoin.tenant_id == workspace_id,
            Account.status == AccountStatus.ACTIVE,
        )
        .order_by(TenantAccountJoin.created_at.asc())
        .limit(1)
    )
    account = db.session.scalar(stmt)
    if account is not None:
        account.set_tenant_id(workspace_id)
        return account

    raise ValueError(f"no active account found for workspace {workspace_id}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/tool-providers/<path:provider>/credentials")
class ProvisioningToolProviderCredentialApi(Resource):
    """CRUD for builtin tool provider credentials."""

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_get_tool_provider_credentials")
    @admin_api_ns.doc(description="Get credentials for a builtin tool provider")
    def get(self, workspace_id: str, provider: str):
        credentials_list = BuiltinToolManageService.get_builtin_tool_provider_credentials(
            tenant_id=workspace_id, provider_name=provider
        )

        if not credentials_list:
            return jsonable_encoder({"credentials": {}, "credential_id": None})

        # Return the default credential (first in list is default)
        default_cred = credentials_list[0]
        return jsonable_encoder({"credentials": default_cred.credentials, "credential_id": default_cred.id})

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_create_tool_provider_credential")
    @admin_api_ns.doc(description="Create a new credential for a builtin tool provider")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningToolCredentialCreatePayload.__name__])
    def post(self, workspace_id: str, provider: str):
        args = ProvisioningToolCredentialCreatePayload.model_validate(admin_api_ns.payload or {})
        account = _get_system_account(workspace_id)

        BuiltinToolManageService.add_builtin_tool_provider(
            user_id=account.id,
            tenant_id=workspace_id,
            provider=provider,
            credentials=args.credentials,
            name=args.name,
            api_type=CredentialType(args.credential_type),
        )

        # Read back to get the credential_id
        credentials_list = BuiltinToolManageService.get_builtin_tool_provider_credentials(
            tenant_id=workspace_id, provider_name=provider
        )

        credential_id = None
        # Match by name if provided, otherwise take the default (newest)
        if args.name:
            for cred in credentials_list:
                if cred.name == args.name:
                    credential_id = cred.id
                    break

        if not credential_id and credentials_list:
            credential_id = credentials_list[0].id

        return jsonable_encoder({"result": "success", "credential_id": credential_id}), 201

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_update_tool_provider_credential")
    @admin_api_ns.doc(description="Update an existing credential for a builtin tool provider")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningToolCredentialUpdatePayload.__name__])
    def put(self, workspace_id: str, provider: str):
        args = ProvisioningToolCredentialUpdatePayload.model_validate(admin_api_ns.payload or {})
        account = _get_system_account(workspace_id)

        BuiltinToolManageService.update_builtin_tool_provider(
            user_id=account.id,
            tenant_id=workspace_id,
            provider=provider,
            credential_id=args.credential_id,
            credentials=args.credentials,
            name=args.name,
        )

        return {"result": "success"}

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_delete_tool_provider_credential")
    @admin_api_ns.doc(description="Delete a credential for a builtin tool provider")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningToolCredentialDeletePayload.__name__])
    def delete(self, workspace_id: str, provider: str):
        args = ProvisioningToolCredentialDeletePayload.model_validate(admin_api_ns.payload or {})

        BuiltinToolManageService.delete_builtin_tool_provider(
            tenant_id=workspace_id,
            provider=provider,
            credential_id=args.credential_id,
        )

        return {"result": "success"}, 204
