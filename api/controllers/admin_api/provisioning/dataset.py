# Copyright Dify Corp. 2025
# SPDX-License-Identifier: MPL-2.0

from flask import abort, g, request
from flask_restx import Resource, fields, marshal
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from controllers.admin_api import admin_api_ns
from controllers.admin_api.wraps import admin_api_only
from controllers.common.schema import register_schema_models
from controllers.console.datasets.datasets import (
    _validate_indexing_technique,
    dataset_detail_fields,
)
from controllers.console.wraps import setup_required
from core.rag.index_processor.constant.index_type import IndexTechniqueType
from extensions.ext_database import db
from models.account import Account, AccountStatus
from models.dataset import Dataset, DatasetPermissionEnum
from services.dataset_service import DatasetService


def _get_active_account(email: str) -> Account | None:
    """Look up an active account by email."""
    account = db.session.scalar(select(Account).where(Account.email == email).limit(1))
    if account is None or account.status != AccountStatus.ACTIVE:
        return None
    return account


class ProvisioningDatasetCreatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    description: str = Field("", max_length=400)
    indexing_technique: str | None = None
    permission: DatasetPermissionEnum | None = DatasetPermissionEnum.ONLY_ME
    process_rule: dict[str, object] | None = None
    embedding_model: str | None = None
    embedding_model_provider: str | None = None
    creator_email: str = Field(..., description="Email of the account that will own this dataset")

    @field_validator("indexing_technique")
    @classmethod
    def validate_indexing(cls, value: str | None) -> str | None:
        return _validate_indexing_technique(value)


class ProvisioningDatasetUpdatePayload(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=40)
    description: str | None = Field(None, max_length=400)
    permission: DatasetPermissionEnum | None = None
    indexing_technique: str | None = None
    process_rule: dict[str, object] | None = None
    embedding_model: str | None = None
    embedding_model_provider: str | None = None

    @field_validator("indexing_technique")
    @classmethod
    def validate_indexing(cls, value: str | None) -> str | None:
        return _validate_indexing_technique(value)


register_schema_models(
    admin_api_ns,
    ProvisioningDatasetCreatePayload,
    ProvisioningDatasetUpdatePayload,
)


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/datasets")
class ProvisioningDatasetListApi(Resource):
    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_list_datasets")
    @admin_api_ns.doc(description="List all datasets in workspace")
    def get(self, workspace_id: str):
        datasets = DatasetService.get_datasets_by_tenant_id(workspace_id)
        return marshal(datasets, dataset_detail_fields)

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_create_dataset")
    @admin_api_ns.doc(description="Create a new dataset")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningDatasetCreatePayload.__name__])
    def post(self, workspace_id: str):
        args = ProvisioningDatasetCreatePayload.model_validate(admin_api_ns.payload or {})
        account = _get_active_account(args.creator_email)
        if account is None:
            abort(404, description=f"account '{args.creator_email}' not found or inactive")

        account.set_tenant_id(workspace_id)

        # Make current_user proxy resolve to this account for service layer
        g._login_user = account

        try:
            dataset = DatasetService.create_empty_dataset(
                tenant_id=workspace_id,
                name=args.name,
                description=args.description,
                indexing_technique=args.indexing_technique,
                account=account,
                permission=args.permission or DatasetPermissionEnum.ONLY_ME,
                provider="vendor",
            )
        except Exception as e:
            abort(500, description=str(e))

        return marshal(dataset, dataset_detail_fields), 201


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/datasets/<string:dataset_id>")
class ProvisioningDatasetApi(Resource):
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_get_dataset")
    @admin_api_ns.doc(description="Get dataset details")
    def get(self, workspace_id: str, dataset_id: str):
        dataset = DatasetService.get_dataset(dataset_id)
        if not dataset or dataset.tenant_id != workspace_id:
            abort(404, description="Dataset not found")
        return marshal(dataset, dataset_detail_fields)

    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_update_dataset")
    @admin_api_ns.doc(description="Update dataset settings")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningDatasetUpdatePayload.__name__])
    def patch(self, workspace_id: str, dataset_id: str):
        dataset = DatasetService.get_dataset(dataset_id)
        if not dataset or dataset.tenant_id != workspace_id:
            abort(404, description="Dataset not found")

        args = ProvisioningDatasetUpdatePayload.model_validate(admin_api_ns.payload or {})

        # Update basic fields
        if args.name is not None:
            dataset.name = args.name
        if args.description is not None:
            dataset.description = args.description
        if args.permission is not None:
            dataset.permission = args.permission
        if args.indexing_technique is not None:
            dataset.indexing_technique = args.indexing_technique

        # Update process rule if provided
        if args.process_rule is not None:
            from services.dataset_service import DatasetProcessRule
            if dataset.dataset_process_rule_id:
                # Update existing process rule
                process_rule = DatasetProcessRule.query.get(dataset.dataset_process_rule_id)
                if process_rule:
                    process_rule.rules_dict = args.process_rule
            else:
                # Create new process rule
                process_rule = DatasetProcessRule(
                    tenant_id=workspace_id,
                    rules_dict=args.process_rule,
                )
                process_rule.save()
                dataset.dataset_process_rule_id = process_rule.id

        # Update embedding model if provided
        if args.embedding_model is not None:
            dataset.embedding_model = args.embedding_model
        if args.embedding_model_provider is not None:
            dataset.embedding_model_provider = args.embedding_model_provider

        dataset.save()
        return marshal(dataset, dataset_detail_fields)

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_delete_dataset")
    @admin_api_ns.doc(description="Delete dataset")
    def delete(self, workspace_id: str, dataset_id: str):
        dataset = DatasetService.get_dataset(dataset_id)
        if not dataset or dataset.tenant_id != workspace_id:
            abort(404, description="Dataset not found")

        account = db.session.get(Account, dataset.created_by)
        if account is None:
            abort(404, description="dataset owner account not found")

        account.set_tenant_id(workspace_id)

        # Make current_user proxy resolve to this account for service layer
        g._login_user = account

        try:
            DatasetService.delete_dataset(dataset_id, account)
        except Exception as e:
            abort(500, description=str(e))

        return {"result": "success"}, 204
