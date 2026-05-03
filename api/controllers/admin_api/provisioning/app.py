"""Provisioning admin API for app lifecycle management.

Provides CRUD endpoints for Dify applications, driven by DSL YAML content.
Authenticated via ``X-Admin-Api-Key`` (``admin_api_only``).
"""

from flask import request
from flask_restx import Resource
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from controllers.admin_api import admin_api_ns
from controllers.admin_api.wraps import admin_api_only
from controllers.common.schema import register_schema_models
from controllers.console.wraps import setup_required
from extensions.ext_database import db
from models import Account, App
from models.account import AccountStatus
from services.app_dsl_service import AppDslService
from services.app_service import AppService
from services.entities.dsl_entities import ImportMode, ImportStatus


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


class ProvisioningAppCreatePayload(BaseModel):
    yaml_content: str = Field(description="YAML DSL content defining the app")
    creator_email: str = Field(description="Email of the workspace member who will own the app")
    name: str | None = Field(default=None, description="Override app name from DSL")
    description: str | None = Field(default=None, description="Override app description from DSL")


class ProvisioningAppUpdatePayload(BaseModel):
    yaml_content: str = Field(description="Updated YAML DSL content")
    name: str | None = Field(default=None, description="Override app name from DSL")
    description: str | None = Field(default=None, description="Override app description from DSL")


class ProvisioningAppListQuery(BaseModel):
    mode: str | None = Field(default=None, description="Filter by app mode")


register_schema_models(admin_api_ns, ProvisioningAppCreatePayload, ProvisioningAppUpdatePayload, ProvisioningAppListQuery)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_account(email: str) -> Account | None:
    """Look up an active account by email."""
    account = db.session.scalar(select(Account).where(Account.email == email).limit(1))
    if account is None or account.status != AccountStatus.ACTIVE:
        return None
    return account


def _get_system_account(workspace_id: str) -> Account:
    """Return the first active owner/admin account in the workspace."""
    from models.account import TenantAccountJoin, TenantAccountJoinRole

    stmt = (
        select(Account)
        .join(TenantAccountJoin, TenantAccountJoin.account_id == Account.id)
        .where(
            TenantAccountJoin.tenant_id == workspace_id,
            Account.status == AccountStatus.ACTIVE,
            TenantAccountJoin.role.in_([TenantAccountJoinRole.OWNER, TenantAccountJoinRole.ADMIN]),
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/apps")
class ProvisioningAppListApi(Resource):
    """List apps in a workspace."""

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_list_apps")
    @admin_api_ns.doc(description="List apps in a workspace")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningAppListQuery.__name__])
    def get(self, workspace_id: str):
        args = ProvisioningAppListQuery.model_validate(request.args.to_dict(flat=True))

        stmt = select(App).where(App.tenant_id == workspace_id, App.is_universal == False)
        if args.mode:
            stmt = stmt.where(App.mode == args.mode)

        apps = db.session.scalars(stmt.order_by(App.created_at.desc())).all()

        result = []
        for app in apps:
            result.append(
                {
                    "id": str(app.id),
                    "name": app.name,
                    "mode": app.mode,
                    "description": app.description,
                    "icon_type": app.icon_type,
                    "icon": app.icon,
                    "icon_background": app.icon_background,
                    "enable_site": app.enable_site,
                    "enable_api": app.enable_api,
                    "created_at": app.created_at.isoformat() + "Z" if app.created_at else None,
                    "updated_at": app.updated_at.isoformat() + "Z" if app.updated_at else None,
                }
            )
        return {"data": result}

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_create_app")
    @admin_api_ns.doc(description="Create an app from DSL YAML content")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningAppCreatePayload.__name__])
    @admin_api_ns.doc(
        responses={
            200: "App created successfully",
            202: "Import pending (DSL version mismatch)",
            400: "Import failed",
            404: "Creator account not found or inactive",
        }
    )
    def post(self, workspace_id: str):
        args = ProvisioningAppCreatePayload.model_validate(admin_api_ns.payload or {})

        account = _get_active_account(args.creator_email)
        if account is None:
            return {"message": f"account '{args.creator_email}' not found or inactive"}, 404

        account.set_tenant_id(workspace_id)

        with Session(db.engine, expire_on_commit=False) as session:
            dsl_service = AppDslService(session)
            result = dsl_service.import_app(
                account=account,
                import_mode=ImportMode.YAML_CONTENT,
                yaml_content=args.yaml_content,
                name=args.name,
                description=args.description,
            )
            if result.status == ImportStatus.FAILED:
                session.rollback()
            else:
                session.commit()

        if result.status == ImportStatus.FAILED:
            return result.model_dump(mode="json"), 400
        if result.status == ImportStatus.PENDING:
            return result.model_dump(mode="json"), 202
        return result.model_dump(mode="json"), 200


@admin_api_ns.route("/provisioning/workspaces/<string:workspace_id>/apps/<string:app_id>")
class ProvisioningAppApi(Resource):
    """Get, update, or delete a specific app."""

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_get_app")
    @admin_api_ns.doc(description="Get app detail with DSL export")
    @admin_api_ns.doc(
        responses={
            200: "App detail with DSL",
            404: "App not found",
        }
    )
    def get(self, workspace_id: str, app_id: str):
        try:
            app_model = db.session.get(App, app_id)
        except DataError:
            return {"message": "app not found"}, 404
        if not app_model or str(app_model.tenant_id) != workspace_id:
            return {"message": "app not found"}, 404

        include_secret = request.args.get("include_secret", "true").lower() == "true"
        dsl_yaml = AppDslService.export_dsl(app_model=app_model, include_secret=include_secret)

        return {
            "id": str(app_model.id),
            "name": app_model.name,
            "mode": app_model.mode,
            "description": app_model.description,
            "icon_type": app_model.icon_type,
            "icon": app_model.icon,
            "icon_background": app_model.icon_background,
            "enable_site": app_model.enable_site,
            "enable_api": app_model.enable_api,
            "dsl_yaml": dsl_yaml,
            "created_at": app_model.created_at.isoformat() + "Z" if app_model.created_at else None,
            "updated_at": app_model.updated_at.isoformat() + "Z" if app_model.updated_at else None,
        }

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_update_app")
    @admin_api_ns.doc(description="Update an app by re-importing DSL YAML content")
    @admin_api_ns.expect(admin_api_ns.models[ProvisioningAppUpdatePayload.__name__])
    @admin_api_ns.doc(
        responses={
            200: "App updated successfully",
            202: "Import pending",
            400: "Import failed",
            404: "App not found",
        }
    )
    def put(self, workspace_id: str, app_id: str):
        try:
            app_model = db.session.get(App, app_id)
        except DataError:
            return {"message": "app not found"}, 404
        if not app_model or str(app_model.tenant_id) != workspace_id:
            return {"message": "app not found"}, 404

        args = ProvisioningAppUpdatePayload.model_validate(admin_api_ns.payload or {})

        with Session(db.engine, expire_on_commit=False) as session:
            dsl_service = AppDslService(session)
            result = dsl_service.import_app(
                account=_get_system_account(workspace_id),
                import_mode=ImportMode.YAML_CONTENT,
                yaml_content=args.yaml_content,
                name=args.name,
                description=args.description,
                app_id=app_id,
            )
            if result.status == ImportStatus.FAILED:
                session.rollback()
            else:
                session.commit()

        if result.status == ImportStatus.FAILED:
            return result.model_dump(mode="json"), 400
        if result.status == ImportStatus.PENDING:
            return result.model_dump(mode="json"), 202
        return result.model_dump(mode="json"), 200

    @setup_required
    @admin_api_only
    @admin_api_ns.doc("admin_provisioning_delete_app")
    @admin_api_ns.doc(description="Delete an app")
    @admin_api_ns.doc(
        responses={
            204: "App deleted",
            404: "App not found",
        }
    )
    def delete(self, workspace_id: str, app_id: str):
        try:
            app_model = db.session.get(App, app_id)
        except DataError:
            return {"message": "app not found"}, 404
        if not app_model or str(app_model.tenant_id) != workspace_id:
            return {"message": "app not found"}, 404

        app_service = AppService()
        app_service.delete_app(app_model)
        return {"result": "success"}, 204
