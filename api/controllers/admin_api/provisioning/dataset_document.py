# Copyright Dify Corp. 2025
# SPDX-License-Identifier: MPL-2.0

from flask import abort, request
from flask_restx import Resource
from pydantic import BaseModel, Field

from controllers.admin_api import admin_api_ns
from controllers.admin_api.wraps import admin_api_only
from controllers.console.wraps import account_initialization_required
from controllers.console.datasets.datasets_document import DocumentResponse
from libs.login import current_account_with_tenant
from models.dataset import Document
from services.dataset_service import DocumentService


class ProvisioningDocumentCreatePayload(BaseModel):
    data_source_type: str = Field(..., description="upload_file or text")
    data_source_info: dict[str, object] = Field(..., description="File or text content")
    indexing_technique: str | None = None
    embedding_model: str | None = None
    embedding_model_provider: str | None = None


@admin_api_ns.route("/provisioning/workspaces/<workspace_id>/datasets/<dataset_id>/documents/<document_id>")
class ProvisioningDocumentApi(Resource):
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_get_document")
    @admin_api_ns.doc(description="Get document details")
    def get(self, workspace_id: str, dataset_id: str, document_id: str):
        document = DocumentService.get_document(dataset_id, document_id)
        if not document or document.tenant_id != workspace_id:
            abort(404, description="Document not found")
        return DocumentResponse.model_validate(document, from_attributes=True).model_dump(mode="json")

    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_delete_document")
    @admin_api_ns.doc(description="Delete document")
    def delete(self, workspace_id: str, dataset_id: str, document_id: str):
        document = DocumentService.get_document(dataset_id, document_id)
        if not document or document.tenant_id != workspace_id:
            abort(404, description="Document not found")

        dataset = document.dataset
        try:
            DocumentService.delete_documents(dataset, [document_id])
        except Exception as e:
            abort(500, description=str(e))

        return {"result": "success"}, 204


@admin_api_ns.route("/provisioning/workspaces/<workspace_id>/datasets/<dataset_id>/documents")
class ProvisioningDocumentListApi(Resource):
    @admin_api_only
    @account_initialization_required
    @admin_api_ns.doc("admin_provisioning_create_document")
    @admin_api_ns.doc(description="Upload document to dataset")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningDocumentCreatePayload.__name__])
    def post(self, workspace_id: str, dataset_id: str):
        args = ProvisioningDocumentCreatePayload.model_validate(admin_api_ns.payload or {})
        account, _ = current_account_with_tenant()

        # Create document
        from services.dataset_service import DatasetService
        dataset = DatasetService.get_dataset(dataset_id)
        if not dataset or dataset.tenant_id != workspace_id:
            abort(404, description="Dataset not found")

        # Create data source
        from services.entities.knowledge_entities.knowledge_entities import DataSource
        data_source = DataSource(
            type=args.data_source_type,
            info_dict=args.data_source_info,
        )

        # Create process rule from dataset if not provided
        from services.dataset_service import DatasetProcessRule
        process_rule = None
        if dataset.dataset_process_rule_id:
            process_rule = DatasetProcessRule.query.get(dataset.dataset_process_rule_id)

        # Create document
        try:
            document = DocumentService.create_document(
                tenant_id=workspace_id,
                dataset=dataset,
                account=account,
                data_source=data_source,
                process_rule=process_rule,
                indexing_technique=args.indexing_technique or dataset.indexing_technique,
                embedding_model=args.embedding_model or dataset.embedding_model,
                embedding_model_provider=args.embedding_model_provider or dataset.embedding_model_provider,
            )
        except Exception as e:
            abort(500, description=str(e))

        return DocumentResponse.model_validate(document, from_attributes=True).model_dump(mode="json"), 201
