"""Provisioning inner API for model provider credential management.

Provides CRUD endpoints for model provider credentials within a workspace.
Authenticated via ``X-Inner-Api-Key`` (``enterprise_inner_api_only``).
"""

from typing import Any

from flask_restx import Resource
from pydantic import BaseModel, Field, field_validator

from controllers.common.schema import register_schema_models
from controllers.console.wraps import setup_required
from controllers.inner_api import inner_api_ns
from controllers.inner_api.wraps import enterprise_inner_api_only
from graphon.model_runtime.errors.validate import CredentialsValidateFailedError
from libs.helper import uuid_value
from services.model_provider_service import ModelProviderService


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class ProvisioningCredentialCreatePayload(BaseModel):
    credentials: dict[str, Any] = Field(description="Provider credentials key-value map")
    name: str | None = Field(default=None, description="Credential name", max_length=30)


class ProvisioningCredentialUpdatePayload(BaseModel):
    credential_id: str = Field(description="ID of the credential to update")
    credentials: dict[str, Any] = Field(description="Updated credentials key-value map")
    name: str | None = Field(default=None, description="Credential name", max_length=30)

    @field_validator("credential_id")
    @classmethod
    def validate_credential_id(cls, value: str) -> str:
        return uuid_value(value)


class ProvisioningCredentialDeletePayload(BaseModel):
    credential_id: str = Field(description="ID of the credential to delete")

    @field_validator("credential_id")
    @classmethod
    def validate_credential_id(cls, value: str) -> str:
        return uuid_value(value)


class ProvisioningCredentialSwitchPayload(BaseModel):
    credential_id: str = Field(description="ID of the credential to switch to")

    @field_validator("credential_id")
    @classmethod
    def validate_credential_id(cls, value: str) -> str:
        return uuid_value(value)


register_schema_models(
    inner_api_ns,
    ProvisioningCredentialCreatePayload,
    ProvisioningCredentialUpdatePayload,
    ProvisioningCredentialDeletePayload,
    ProvisioningCredentialSwitchPayload,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@inner_api_ns.route("/provisioning/workspaces/<string:workspace_id>/model-providers/<path:provider>/credentials")
class ProvisioningModelProviderCredentialApi(Resource):
    """CRUD for model provider credentials."""

    @setup_required
    @enterprise_inner_api_only
    @inner_api_ns.doc("provisioning_get_model_provider_credentials")
    @inner_api_ns.doc(description="Get credentials for a model provider")
    def get(self, workspace_id: str, provider: str):
        service = ModelProviderService()
        credentials = service.get_provider_credential(tenant_id=workspace_id, provider=provider)
        return {"credentials": credentials}

    @setup_required
    @enterprise_inner_api_only
    @inner_api_ns.doc("provisioning_create_model_provider_credential")
    @inner_api_ns.doc(description="Create a new credential for a model provider")
    @inner_api_ns.expect(inner_api_ns.models[ProvisioningCredentialCreatePayload.__name__])
    def post(self, workspace_id: str, provider: str):
        args = ProvisioningCredentialCreatePayload.model_validate(inner_api_ns.payload or {})

        service = ModelProviderService()
        try:
            service.create_provider_credential(
                tenant_id=workspace_id,
                provider=provider,
                credentials=args.credentials,
                credential_name=args.name,
            )
        except CredentialsValidateFailedError as ex:
            return {"message": str(ex)}, 400

        return {"result": "success"}, 201

    @setup_required
    @enterprise_inner_api_only
    @inner_api_ns.doc("provisioning_update_model_provider_credential")
    @inner_api_ns.doc(description="Update an existing credential for a model provider")
    @inner_api_ns.expect(inner_api_ns.models[ProvisioningCredentialUpdatePayload.__name__])
    def put(self, workspace_id: str, provider: str):
        args = ProvisioningCredentialUpdatePayload.model_validate(inner_api_ns.payload or {})

        service = ModelProviderService()
        try:
            service.update_provider_credential(
                tenant_id=workspace_id,
                provider=provider,
                credentials=args.credentials,
                credential_id=args.credential_id,
                credential_name=args.name,
            )
        except CredentialsValidateFailedError as ex:
            return {"message": str(ex)}, 400

        return {"result": "success"}

    @setup_required
    @enterprise_inner_api_only
    @inner_api_ns.doc("provisioning_delete_model_provider_credential")
    @inner_api_ns.doc(description="Delete a credential for a model provider")
    @inner_api_ns.expect(inner_api_ns.models[ProvisioningCredentialDeletePayload.__name__])
    def delete(self, workspace_id: str, provider: str):
        args = ProvisioningCredentialDeletePayload.model_validate(inner_api_ns.payload or {})

        service = ModelProviderService()
        service.remove_provider_credential(
            tenant_id=workspace_id,
            provider=provider,
            credential_id=args.credential_id,
        )

        return {"result": "success"}, 204


@inner_api_ns.route(
    "/provisioning/workspaces/<string:workspace_id>/model-providers/<path:provider>/credentials/switch"
)
class ProvisioningModelProviderCredentialSwitchApi(Resource):
    """Switch the active credential for a model provider."""

    @setup_required
    @enterprise_inner_api_only
    @inner_api_ns.doc("provisioning_switch_model_provider_credential")
    @inner_api_ns.doc(description="Switch the active credential for a model provider")
    @inner_api_ns.expect(inner_api_ns.models[ProvisioningCredentialSwitchPayload.__name__])
    def post(self, workspace_id: str, provider: str):
        args = ProvisioningCredentialSwitchPayload.model_validate(inner_api_ns.payload or {})

        service = ModelProviderService()
        service.switch_active_provider_credential(
            tenant_id=workspace_id,
            provider=provider,
            credential_id=args.credential_id,
        )

        return {"result": "success"}


@inner_api_ns.route("/provisioning/workspaces/<string:workspace_id>/model-providers")
class ProvisioningModelProviderListApi(Resource):
    """List model providers for a workspace."""

    @setup_required
    @enterprise_inner_api_only
    @inner_api_ns.doc("provisioning_list_model_providers")
    @inner_api_ns.doc(description="List model providers for a workspace")
    def get(self, workspace_id: str):
        service = ModelProviderService()
        provider_list = service.get_provider_list(tenant_id=workspace_id)
        return {"data": provider_list}
