# Copyright Dify Corp. 2025
# SPDX-License-Identifier: MPL-2.0

from flask import abort, g, request
from flask_restx import Resource
from pydantic import BaseModel, Field
from sqlalchemy import select

from controllers.admin_api import admin_api_ns
from controllers.admin_api.wraps import admin_api_only
from controllers.common.schema import register_schema_models
from controllers.console.wraps import setup_required
from controllers.console.datasets.datasets_document import DocumentResponse
from extensions.ext_database import db
from models.account import Account, AccountStatus
from models.dataset import Document
from services.dataset_service import DocumentService


def _get_active_account(email: str) -> Account | None:
    """Look up an active account by email."""
    account = db.session.scalar(select(Account).where(Account.email == email).limit(1))
    if account is None or account.status != AccountStatus.ACTIVE:
        return None
    return account


class ProvisioningDocumentCreatePayload(BaseModel):
    data_source_type: str = Field(..., description="upload_file or text")
    data_source_info: dict[str, object] = Field(
        ...,
        description=(
            "For text type: {\"text_content\": \"...\", \"text_name\": \"...\"}. "
            "For upload_file type: {\"file_ids\": [\"id1\"]}."
        ),
    )
    indexing_technique: str | None = None
    embedding_model: str | None = None
    embedding_model_provider: str | None = None
    creator_email: str = Field(..., description="Email of the account that will own this document")


register_schema_models(admin_api_ns, ProvisioningDocumentCreatePayload)


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/datasets/<string:dataset_id>/documents/<string:document_id>")
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


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/datasets/<string:dataset_id>/documents")
class ProvisioningDocumentListApi(Resource):
    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_create_document")
    @admin_api_ns.doc(description="Upload document to dataset")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningDocumentCreatePayload.__name__])
    def post(self, workspace_id: str, dataset_id: str):
        args = ProvisioningDocumentCreatePayload.model_validate(admin_api_ns.payload or {})
        account = _get_active_account(args.creator_email)
        if account is None:
            abort(404, description=f"account '{args.creator_email}' not found or inactive")

        account.set_tenant_id(workspace_id)

        # Make current_user proxy resolve to this account for service layer
        g._login_user = account

        # Create document
        from services.dataset_service import DatasetService
        dataset = DatasetService.get_dataset(dataset_id)
        if not dataset or dataset.tenant_id != workspace_id:
            abort(404, description="Dataset not found")

        # Build data source based on type
        from services.entities.knowledge_entities.knowledge_entities import DataSource, FileInfo, InfoList

        if args.data_source_type == "text":
            # For text content: upload as file first, then reference the file ID
            text_content = args.data_source_info.get("text_content", "")
            text_name = args.data_source_info.get("text_name", "text.txt")

            from services.file_service import FileService
            upload_file = FileService(db.engine).upload_text(
                text=text_content,
                text_name=text_name,
                user_id=str(account.id),
                tenant_id=workspace_id,
            )

            data_source = DataSource(
                info_list=InfoList(
                    data_source_type="upload_file",
                    file_info_list=FileInfo(file_ids=[str(upload_file.id)]),
                ),
            )
        elif args.data_source_type == "upload_file":
            file_ids = args.data_source_info.get("file_ids", [])
            data_source = DataSource(
                info_list=InfoList(
                    data_source_type="upload_file",
                    file_info_list=FileInfo(file_ids=[str(fid) for fid in file_ids]),
                ),
            )
        else:
            abort(400, description=f"Unsupported data_source_type: {args.data_source_type}")

        # Build process rule from dataset
        from services.entities.knowledge_entities.knowledge_entities import ProcessRule
        process_rule = None
        rule_row = dataset.latest_process_rule
        if rule_row:
            process_rule = ProcessRule(
                mode=rule_row.mode,
                rules=rule_row.rules_dict if rule_row.mode != "automatic" else None,
            )
        if process_rule is None:
            process_rule = ProcessRule(mode="automatic")

        # Build knowledge config and save document
        from services.entities.knowledge_entities.knowledge_entities import KnowledgeConfig
        knowledge_config = KnowledgeConfig(
            indexing_technique=args.indexing_technique or dataset.indexing_technique or "high_quality",
            data_source=data_source,
            process_rule=process_rule,
            embedding_model=args.embedding_model or dataset.embedding_model,
            embedding_model_provider=args.embedding_model_provider or dataset.embedding_model_provider,
        )

        try:
            documents, batch = DocumentService.save_document_with_dataset_id(
                dataset=dataset,
                knowledge_config=knowledge_config,
                account=account,
                created_from="api",
            )
            document = documents[0] if documents else None
            if document is None:
                abort(500, description="Failed to create document")
        except Exception as e:
            abort(500, description=str(e))

        return DocumentResponse.model_validate(document, from_attributes=True).model_dump(mode="json"), 201
