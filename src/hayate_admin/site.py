"""Fail-closed admin route registration and operation orchestration."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from urllib.parse import quote, urlsplit

from hayate import (
    Context,
    File,
    FormDataLimitError,
    FormDataLimits,
    Hayate,
    Response,
    problem,
)
from hayate_htmx import HtmxRequest, with_htmx

from .contracts import (
    Actor,
    AdminAction,
    AdminAsset,
    AdminBulkAction,
    AdminResource,
    AdminValidationError,
    AuditEvent,
    AuditPhase,
    AuditSink,
    AuditSinkFactory,
    Authorizer,
    BulkActionResult,
    ListQuery,
    Page,
    Record,
)
from .render import AdminRenderer

_FORM_BODY_LIMIT = 64 * 1024
_PREFIX = re.compile(r"^/[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*$")


def _normalize_origin(origin: str) -> str:
    if not isinstance(origin, str):
        raise ValueError(f"invalid admin allowed origin: {origin!r}")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"invalid admin allowed origin: {origin!r}")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _normalize_prefix(prefix: str) -> str:
    if not isinstance(prefix, str):
        raise ValueError("admin prefix must be a non-root static absolute path")
    value = prefix.rstrip("/")
    if not _PREFIX.fullmatch(value):
        raise ValueError("admin prefix must be a non-root static absolute path")
    return value


class AdminSite:
    """Register an internal CRUD surface onto an ordinary Hayate application."""

    __slots__ = (
        "_audit",
        "_audit_factory",
        "_authorize",
        "_registered",
        "_renderer",
        "_resources",
        "_trusted_origins",
        "prefix",
        "title",
    )

    def __init__(
        self,
        *,
        title: str,
        allowed_origins: set[str] | frozenset[str],
        authorize: Authorizer,
        audit: AuditSink | None = None,
        audit_factory: AuditSinkFactory | None = None,
        prefix: str = "/admin",
        htmx_asset: AdminAsset | None = None,
    ) -> None:
        if not isinstance(title, str) or not title or len(title) > 120:
            raise ValueError("admin title must be 1-120 characters")
        if not isinstance(allowed_origins, (set, frozenset)) or not allowed_origins:
            raise ValueError("admin allowed_origins must not be empty")
        if not callable(authorize):
            raise ValueError("admin authorize must be callable")
        if (audit is None) == (audit_factory is None):
            raise ValueError("admin requires exactly one audit sink or audit_factory")
        if audit is not None and not callable(audit):
            raise ValueError("admin audit must be callable")
        if audit_factory is not None and not callable(audit_factory):
            raise ValueError("admin audit_factory must be callable")
        if htmx_asset is not None and not isinstance(htmx_asset, AdminAsset):
            raise ValueError("admin htmx_asset must be an AdminAsset")
        self.title = title
        self.prefix = _normalize_prefix(prefix)
        self._trusted_origins = frozenset(_normalize_origin(origin) for origin in allowed_origins)
        self._authorize = authorize
        self._audit = audit
        self._audit_factory = audit_factory
        self._resources: dict[str, AdminResource] = {}
        self._registered = False
        self._renderer = AdminRenderer(prefix=self.prefix, title=title, asset=htmx_asset)

    @property
    def resources(self) -> tuple[AdminResource, ...]:
        return tuple(self._resources.values())

    def add(self, resource: AdminResource) -> AdminResource:
        """Add one resource before the site is registered."""
        if not isinstance(resource, AdminResource):
            raise ValueError("admin resource must be an AdminResource")
        if self._registered:
            raise RuntimeError("admin resources cannot be added after route registration")
        if resource.slug in self._resources:
            raise ValueError(f"duplicate admin resource slug: {resource.slug!r}")
        self._resources[resource.slug] = resource
        return resource

    def register(self, app: Hayate) -> None:
        """Register the complete route set exactly once."""
        if self._registered:
            raise RuntimeError("admin site is already registered")
        if not self._resources:
            raise RuntimeError("admin site requires at least one resource")
        self._registered = True
        prefix = self.prefix

        @app.get(prefix)
        async def admin_index(context: Context) -> Response:
            return await self._index(context)

        @app.get(f"{prefix}/:resource")
        async def admin_list(context: Context) -> Response:
            return await self._list(context)

        @app.get(f"{prefix}/:resource/create")
        async def admin_create_form(context: Context) -> Response:
            return await self._create_form(context)

        @app.post(f"{prefix}/:resource/create")
        async def admin_create(context: Context) -> Response:
            return await self._create(context)

        @app.post(f"{prefix}/:resource/bulk")
        async def admin_bulk(context: Context) -> Response:
            return await self._bulk(context)

        @app.get(f"{prefix}/:resource/object/:object_id")
        async def admin_detail(context: Context) -> Response:
            return await self._detail(context)

        @app.get(f"{prefix}/:resource/object/:object_id/edit")
        async def admin_edit_form(context: Context) -> Response:
            return await self._edit_form(context)

        @app.post(f"{prefix}/:resource/object/:object_id/edit")
        async def admin_edit(context: Context) -> Response:
            return await self._edit(context)

        @app.get(f"{prefix}/:resource/object/:object_id/delete")
        async def admin_delete_form(context: Context) -> Response:
            return await self._delete_form(context)

        @app.post(f"{prefix}/:resource/object/:object_id/delete")
        async def admin_delete(context: Context) -> Response:
            return await self._delete(context)

    def _resource(self, context: Context) -> AdminResource | None:
        slug = context.req.param("resource")
        return None if slug is None else self._resources.get(slug)

    @staticmethod
    def _object_id(context: Context) -> str | None:
        value = context.req.param("object_id")
        return value if value else None

    async def _allowed(
        self,
        context: Context,
        action: AdminAction,
        resource: AdminResource | None,
        object_id: str | None = None,
    ) -> Actor | None:
        return await self._authorize(context, action, resource, object_id)

    @staticmethod
    def _forbidden() -> Response:
        return problem(403, title="Admin operation forbidden")

    @staticmethod
    def _not_found() -> Response:
        return problem(404, title="Admin record not found")

    async def _index(self, context: Context) -> Response:
        actor = await self._allowed(context, "site:view", None)
        if actor is None:
            return self._forbidden()
        visible = []
        for resource in self._resources.values():
            if await self._allowed(context, "resource:view", resource) is not None:
                visible.append(resource)
        content = self._renderer.index(visible)
        return self._renderer.response(
            context,
            title=self.title,
            actor=actor,
            content=content,
        )

    async def _list(self, context: Context) -> Response:
        resource = self._resource(context)
        if resource is None:
            return self._not_found()
        actor = await self._allowed(context, "resource:view", resource)
        if actor is None:
            return self._forbidden()
        try:
            query = self._list_query(context, resource)
        except ValueError as error:
            return problem(400, title="Invalid admin list query", detail=str(error))
        page = await resource.repository_for(context).list(query)
        self._validate_page(resource, query, page)
        bulk_actions: tuple[AdminBulkAction, ...] = ()
        if resource.bulk_actions and (
            await self._allowed(context, "resource:bulk", resource) is not None
        ):
            visible_actions = []
            for action in resource.bulk_actions:
                if await self._allowed(context, action.required_action, resource) is not None:
                    visible_actions.append(action)
            bulk_actions = tuple(visible_actions)
        content = self._renderer.listing(
            resource,
            page,
            query,
            can_add=await self._allowed(context, "resource:add", resource) is not None,
            can_change=await self._allowed(context, "resource:change", resource) is not None,
            can_delete=await self._allowed(context, "resource:delete", resource) is not None,
            bulk_actions=bulk_actions,
        )
        return self._renderer.response(
            context,
            title=resource.label,
            actor=actor,
            content=content,
        )

    @staticmethod
    def _list_query(context: Context, resource: AdminResource) -> ListQuery:
        search = context.req.query("q")
        if search is not None:
            search = search.strip() or None
        if search is not None and len(search) > 200:
            raise ValueError("search must not exceed 200 characters")

        raw_page = context.req.query("page") or "1"
        try:
            page_number = int(raw_page)
        except ValueError as error:
            raise ValueError("page must be a positive integer") from error
        if not 1 <= page_number <= 1_000_000:
            raise ValueError("page must be in 1-1000000")

        sortable = {field.name for field in resource.fields if field.sortable}
        requested_sort = context.req.query("sort")
        order_by = requested_sort if requested_sort in sortable else None
        descending = order_by is not None and context.req.query("direction") == "desc"

        filters = {}
        for admin_field in resource.fields:
            if not admin_field.filterable:
                continue
            value = context.req.query(f"filter_{admin_field.name}")
            allowed = {choice for choice, _ in admin_field.choices}
            if value in allowed:
                filters[admin_field.name] = value

        return ListQuery(
            search=search,
            filters=filters,
            order_by=order_by,
            descending=descending,
            offset=(page_number - 1) * resource.page_size,
            limit=resource.page_size,
        )

    @staticmethod
    def _validate_page(resource: AdminResource, query: ListQuery, page: Page) -> None:
        if len(page.items) > query.limit:
            raise ValueError(f"{resource.slug}: repository returned more than the requested limit")
        for record in page.items:
            AdminSite._validate_record(resource, record)

    @staticmethod
    def _validate_record(resource: AdminResource, record: Record) -> None:
        if resource.id_field not in record or record[resource.id_field] is None:
            raise ValueError(f"{resource.slug}: repository record is missing its ID")
        unknown = set(record) - set(resource.field_map)
        if unknown:
            raise ValueError(
                f"{resource.slug}: repository exposed undeclared fields: {sorted(unknown)!r}"
            )

    async def _detail(self, context: Context) -> Response:
        resource = self._resource(context)
        object_id = self._object_id(context)
        if resource is None or object_id is None:
            return self._not_found()
        actor = await self._allowed(context, "resource:view", resource, object_id)
        if actor is None:
            return self._forbidden()
        record = await resource.repository_for(context).get(object_id)
        if record is None:
            return self._not_found()
        self._validate_record(resource, record)
        content = self._renderer.detail(
            resource,
            record,
            can_change=await self._allowed(context, "resource:change", resource, object_id)
            is not None,
            can_delete=await self._allowed(context, "resource:delete", resource, object_id)
            is not None,
        )
        return self._renderer.response(
            context,
            title=str(record.get(resource.title_field, object_id)),
            actor=actor,
            content=content,
        )

    async def _create_form(self, context: Context) -> Response:
        resource = self._resource(context)
        if resource is None:
            return self._not_found()
        actor = await self._allowed(context, "resource:add", resource)
        if actor is None:
            return self._forbidden()
        content = self._renderer.form(
            resource,
            action=f"{self.prefix}/{resource.slug}/create",
            heading=f"Add {resource.singular_label}",
            values={},
            errors={},
            submit_label="Create",
        )
        return self._renderer.response(
            context,
            title=f"Add {resource.singular_label}",
            actor=actor,
            content=content,
        )

    async def _create(self, context: Context) -> Response:
        resource = self._resource(context)
        if resource is None:
            return self._not_found()
        guard = await self._guard_mutation(context, "resource:add", resource, None)
        if guard is not None:
            return guard
        actor = await self._allowed(context, "resource:add", resource)
        if actor is None:
            await self._failure(
                context,
                "resource:add",
                resource,
                None,
                None,
                "AuthorizationDenied",
            )
            return self._forbidden()
        await self._event(context, "attempt", "resource:add", resource, None, actor)

        parsed = await self._parse_form(context, resource)
        if isinstance(parsed, Response):
            await self._failure(context, "resource:add", resource, None, actor, "InvalidForm")
            return parsed
        values, display_values, errors = parsed
        if errors:
            await self._failure(
                context,
                "resource:add",
                resource,
                None,
                actor,
                "ValidationError",
            )
            return self._form_error_response(
                context,
                resource,
                actor=actor,
                action=f"{self.prefix}/{resource.slug}/create",
                heading=f"Add {resource.singular_label}",
                values=display_values,
                errors=errors,
                submit_label="Create",
            )
        try:
            record = await resource.repository_for(context).create(values)
        except AdminValidationError as error:
            await self._failure(
                context,
                "resource:add",
                resource,
                None,
                actor,
                type(error).__name__,
            )
            return self._form_error_response(
                context,
                resource,
                actor=actor,
                action=f"{self.prefix}/{resource.slug}/create",
                heading=f"Add {resource.singular_label}",
                values=display_values,
                errors=self._safe_errors(resource, error.errors),
                submit_label="Create",
            )
        except Exception as error:
            await self._failure(
                context,
                "resource:add",
                resource,
                None,
                actor,
                type(error).__name__,
            )
            raise
        object_id = self._record_id(resource, record)
        self._validate_record(resource, record)
        await self._event(context, "success", "resource:add", resource, object_id, actor)
        return self._redirect(context, self._record_location(resource, object_id))

    async def _bulk(self, context: Context) -> Response:
        resource = self._resource(context)
        if resource is None:
            return self._not_found()
        guard = await self._guard_mutation(context, "resource:bulk", resource, None)
        if guard is not None:
            return guard
        actor = await self._allowed(context, "resource:bulk", resource)
        if actor is None:
            await self._failure(
                context,
                "resource:bulk",
                resource,
                None,
                None,
                "AuthorizationDenied",
            )
            return self._forbidden()
        parsed = await self._parse_bulk_form(context, resource, actor)
        if isinstance(parsed, Response):
            await self._failure(
                context,
                "resource:bulk",
                resource,
                None,
                actor,
                "InvalidBulkForm",
            )
            return parsed
        action, object_ids = parsed
        if await self._allowed(context, action.required_action, resource) is None:
            await self._failure(
                context,
                "resource:bulk",
                resource,
                None,
                actor,
                "AuthorizationDenied",
                operation=action.slug,
            )
            return self._forbidden()
        for object_id in object_ids:
            if (
                await self._allowed(
                    context,
                    action.required_action,
                    resource,
                    object_id,
                )
                is None
            ):
                await self._failure(
                    context,
                    "resource:bulk",
                    resource,
                    object_id,
                    actor,
                    "AuthorizationDenied",
                    operation=action.slug,
                )
                return self._forbidden()

        for object_id in object_ids:
            await self._event(
                context,
                "attempt",
                "resource:bulk",
                resource,
                object_id,
                actor,
                operation=action.slug,
            )
        try:
            result = await action.handler(
                context,
                resource.repository_for(context),
                object_ids,
            )
            self._validate_bulk_result(object_ids, result)
        except Exception as error:
            for object_id in object_ids:
                await self._failure(
                    context,
                    "resource:bulk",
                    resource,
                    object_id,
                    actor,
                    type(error).__name__,
                    operation=action.slug,
                )
            raise

        for object_id in result.succeeded:
            await self._event(
                context,
                "success",
                "resource:bulk",
                resource,
                object_id,
                actor,
                operation=action.slug,
            )
        for object_id in result.failed:
            await self._failure(
                context,
                "resource:bulk",
                resource,
                object_id,
                actor,
                "BulkActionFailed",
                operation=action.slug,
            )
        content = self._renderer.bulk_result(resource, action, result)
        return self._renderer.response(
            context,
            title=action.label,
            actor=actor,
            content=content,
        )

    async def _edit_form(self, context: Context) -> Response:
        resource = self._resource(context)
        object_id = self._object_id(context)
        if resource is None or object_id is None:
            return self._not_found()
        actor = await self._allowed(context, "resource:change", resource, object_id)
        if actor is None:
            return self._forbidden()
        record = await resource.repository_for(context).get(object_id)
        if record is None:
            return self._not_found()
        self._validate_record(resource, record)
        action = f"{self._record_location(resource, object_id)}/edit"
        content = self._renderer.form(
            resource,
            action=action,
            heading=f"Edit {record.get(resource.title_field, object_id)}",
            values=record,
            errors={},
            submit_label="Save changes",
        )
        return self._renderer.response(
            context,
            title=f"Edit {record.get(resource.title_field, object_id)}",
            actor=actor,
            content=content,
        )

    async def _edit(self, context: Context) -> Response:
        resource = self._resource(context)
        object_id = self._object_id(context)
        if resource is None or object_id is None:
            return self._not_found()
        guard = await self._guard_mutation(context, "resource:change", resource, object_id)
        if guard is not None:
            return guard
        actor = await self._allowed(context, "resource:change", resource, object_id)
        if actor is None:
            await self._failure(
                context,
                "resource:change",
                resource,
                object_id,
                None,
                "AuthorizationDenied",
            )
            return self._forbidden()
        await self._event(context, "attempt", "resource:change", resource, object_id, actor)

        parsed = await self._parse_form(context, resource)
        if isinstance(parsed, Response):
            await self._failure(
                context,
                "resource:change",
                resource,
                object_id,
                actor,
                "InvalidForm",
            )
            return parsed
        values, display_values, errors = parsed
        action = f"{self._record_location(resource, object_id)}/edit"
        if errors:
            await self._failure(
                context,
                "resource:change",
                resource,
                object_id,
                actor,
                "ValidationError",
            )
            return self._form_error_response(
                context,
                resource,
                actor=actor,
                action=action,
                heading=f"Edit {object_id}",
                values=display_values,
                errors=errors,
                submit_label="Save changes",
            )
        try:
            record = await resource.repository_for(context).update(object_id, values)
        except AdminValidationError as error:
            await self._failure(
                context,
                "resource:change",
                resource,
                object_id,
                actor,
                type(error).__name__,
            )
            return self._form_error_response(
                context,
                resource,
                actor=actor,
                action=action,
                heading=f"Edit {object_id}",
                values=display_values,
                errors=self._safe_errors(resource, error.errors),
                submit_label="Save changes",
            )
        except Exception as error:
            await self._failure(
                context,
                "resource:change",
                resource,
                object_id,
                actor,
                type(error).__name__,
            )
            raise
        if record is None:
            await self._failure(
                context,
                "resource:change",
                resource,
                object_id,
                actor,
                "NotFound",
            )
            return self._not_found()
        self._validate_record(resource, record)
        await self._event(context, "success", "resource:change", resource, object_id, actor)
        return self._redirect(context, self._record_location(resource, object_id))

    async def _delete_form(self, context: Context) -> Response:
        resource = self._resource(context)
        object_id = self._object_id(context)
        if resource is None or object_id is None:
            return self._not_found()
        actor = await self._allowed(context, "resource:delete", resource, object_id)
        if actor is None:
            return self._forbidden()
        record = await resource.repository_for(context).get(object_id)
        if record is None:
            return self._not_found()
        self._validate_record(resource, record)
        action = f"{self._record_location(resource, object_id)}/delete"
        content = self._renderer.delete_confirmation(resource, record, action=action)
        return self._renderer.response(
            context,
            title=f"Delete {record.get(resource.title_field, object_id)}",
            actor=actor,
            content=content,
        )

    async def _delete(self, context: Context) -> Response:
        resource = self._resource(context)
        object_id = self._object_id(context)
        if resource is None or object_id is None:
            return self._not_found()
        guard = await self._guard_mutation(context, "resource:delete", resource, object_id)
        if guard is not None:
            return guard
        actor = await self._allowed(context, "resource:delete", resource, object_id)
        if actor is None:
            await self._failure(
                context,
                "resource:delete",
                resource,
                object_id,
                None,
                "AuthorizationDenied",
            )
            return self._forbidden()
        await self._event(context, "attempt", "resource:delete", resource, object_id, actor)
        try:
            deleted = await resource.repository_for(context).delete(object_id)
        except Exception as error:
            await self._failure(
                context,
                "resource:delete",
                resource,
                object_id,
                actor,
                type(error).__name__,
            )
            raise
        if not deleted:
            await self._failure(
                context,
                "resource:delete",
                resource,
                object_id,
                actor,
                "NotFound",
            )
            return self._not_found()
        await self._event(context, "success", "resource:delete", resource, object_id, actor)
        return self._redirect(context, f"{self.prefix}/{resource.slug}")

    async def _guard_mutation(
        self,
        context: Context,
        action: AdminAction,
        resource: AdminResource,
        object_id: str | None,
    ) -> Response | None:
        fetch_site = (context.req.header("sec-fetch-site") or "").lower()
        if fetch_site not in ("", "same-origin", "same-site", "none"):
            await self._failure(
                context,
                action,
                resource,
                object_id,
                None,
                "CrossSiteRequest",
            )
            return problem(403, title="Cross-site admin mutation rejected")
        origin = context.req.header("origin")
        try:
            normalized = None if origin is None else _normalize_origin(origin)
        except ValueError:
            normalized = None
        if normalized not in self._trusted_origins:
            await self._failure(context, action, resource, object_id, None, "InvalidOrigin")
            return problem(403, title="Admin mutation origin rejected")
        return None

    async def _parse_form(
        self,
        context: Context,
        resource: AdminResource,
    ) -> tuple[Mapping[str, object], Mapping[str, object], Mapping[str, str]] | Response:
        content_type = (context.req.header("content-type") or "").partition(";")[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            return problem(415, title="Admin forms require application/x-www-form-urlencoded")
        limits = FormDataLimits(
            max_body_bytes=_FORM_BODY_LIMIT,
            max_file_bytes=0,
            max_field_bytes=16 * 1024,
            max_parts=len(resource.fields) + 2,
            max_header_bytes=8 * 1024,
            file_memory_bytes=0,
        )
        try:
            form = await context.req.form_data(limits)
        except (FormDataLimitError, TypeError) as form_error:
            return problem(413, title="Admin form rejected", detail=str(form_error))

        allowed = {field.name for field in resource.fields if not field.read_only}
        raw: dict[str, str] = {}
        errors: dict[str, str] = {}
        async with form:
            for name, value in form:
                if name not in allowed:
                    errors["__all__"] = "The form contains an unexpected field."
                    continue
                if name in raw:
                    errors[name] = "Submit exactly one value for this field."
                    continue
                if isinstance(value, File):
                    errors[name] = "File uploads are not supported by this field."
                    continue
                raw[name] = value

        values: dict[str, object] = {}
        display_values: dict[str, object] = dict(raw)
        for admin_field in resource.fields:
            if admin_field.read_only:
                continue
            parsed_value, parse_error = admin_field.parse(raw.get(admin_field.name))
            if admin_field.kind == "checkbox":
                display_values[admin_field.name] = bool(parsed_value)
            if parse_error is not None:
                errors[admin_field.name] = parse_error
            elif parsed_value is not None:
                values[admin_field.name] = parsed_value
        return (
            MappingProxyType(values),
            MappingProxyType(display_values),
            MappingProxyType(errors),
        )

    async def _parse_bulk_form(
        self,
        context: Context,
        resource: AdminResource,
        actor: Actor,
    ) -> tuple[AdminBulkAction, tuple[str, ...]] | Response:
        content_type = (context.req.header("content-type") or "").partition(";")[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            return problem(415, title="Admin forms require application/x-www-form-urlencoded")
        limits = FormDataLimits(
            max_body_bytes=_FORM_BODY_LIMIT,
            max_file_bytes=0,
            max_field_bytes=512,
            max_parts=101,
            max_header_bytes=8 * 1024,
            file_memory_bytes=0,
        )
        try:
            form = await context.req.form_data(limits)
        except (FormDataLimitError, TypeError) as form_error:
            return problem(413, title="Admin bulk form rejected", detail=str(form_error))

        action_slug: str | None = None
        object_ids: list[str] = []
        error: str | None = None
        async with form:
            for name, value in form:
                if isinstance(value, File):
                    error = "File uploads are not accepted by bulk actions."
                elif name == "action":
                    if action_slug is not None:
                        error = "Submit exactly one bulk action."
                    else:
                        action_slug = value
                elif name == "selected":
                    if (
                        not value
                        or len(value) > 255
                        or any(ord(character) < 0x20 for character in value)
                    ):
                        error = "Selected object IDs must be bounded printable strings."
                    else:
                        object_ids.append(value)
                else:
                    error = "The bulk form contains an unexpected field."

        if error is None and action_slug is None:
            error = "Choose a bulk action."
        action = None if action_slug is None else resource.bulk_action_map.get(action_slug)
        if error is None and action is None:
            error = "Choose a registered bulk action."
        unique_ids = tuple(dict.fromkeys(object_ids))
        if error is None and not unique_ids:
            error = "Select at least one record."
        if error is None and action is not None and len(object_ids) > action.max_selected:
            error = f"Select at most {action.max_selected} records."
        if error is not None or action is None:
            content = self._renderer.bulk_error(resource, error or "The bulk form is invalid.")
            return self._renderer.response(
                context,
                title="Bulk action rejected",
                actor=actor,
                content=content,
                status=422,
            )
        return action, unique_ids

    def _form_error_response(
        self,
        context: Context,
        resource: AdminResource,
        *,
        actor: Actor,
        action: str,
        heading: str,
        values: Mapping[str, object],
        errors: Mapping[str, str],
        submit_label: str,
    ) -> Response:
        content = self._renderer.form(
            resource,
            action=action,
            heading=heading,
            values=values,
            errors=errors,
            submit_label=submit_label,
        )
        return self._renderer.response(
            context,
            title=heading,
            actor=actor,
            content=content,
            status=422,
        )

    @staticmethod
    def _safe_errors(resource: AdminResource, errors: Mapping[str, str]) -> Mapping[str, str]:
        allowed = set(resource.field_map) | {"__all__"}
        safe = {
            name if name in allowed else "__all__": message
            for name, message in errors.items()
            if message
        }
        return safe or {"__all__": "The record could not be saved."}

    @staticmethod
    def _validate_bulk_result(
        selected: tuple[str, ...],
        result: BulkActionResult,
    ) -> None:
        if not isinstance(result, BulkActionResult):
            raise TypeError("admin bulk action returned an invalid result")
        returned = tuple(result.succeeded) + tuple(result.failed)
        if len(returned) != len(selected) or set(returned) != set(selected):
            raise ValueError("admin bulk action result must partition every selected object")

    @staticmethod
    def _record_id(resource: AdminResource, record: Record) -> str:
        value = record.get(resource.id_field)
        if value is None:
            raise ValueError(f"{resource.slug}: created record is missing its ID")
        return str(value)

    def _record_location(self, resource: AdminResource, object_id: str) -> str:
        return f"{self.prefix}/{resource.slug}/object/{quote(object_id, safe='')}"

    @staticmethod
    def _redirect(context: Context, location: str) -> Response:
        if HtmxRequest.from_context(context).is_htmx:
            return with_htmx(context.body(None, 204), redirect=location)
        return context.redirect(location, 303)

    async def _event(
        self,
        context: Context,
        phase: AuditPhase,
        action: AdminAction,
        resource: AdminResource,
        object_id: str | None,
        actor: Actor | None,
        error_type: str | None = None,
        operation: str | None = None,
    ) -> None:
        sink = self._audit
        if sink is None:
            factory = self._audit_factory
            if factory is None:
                raise RuntimeError("admin audit configuration is missing")
            sink = factory(context)
        if not callable(sink):
            raise TypeError("admin audit_factory returned an invalid sink")
        await sink(
            AuditEvent(
                occurred_at=datetime.now(UTC),
                phase=phase,
                action=action,
                resource=resource.slug,
                object_id=object_id,
                actor_id=None if actor is None else actor.id,
                error_type=error_type,
                operation=operation,
            )
        )

    async def _failure(
        self,
        context: Context,
        action: AdminAction,
        resource: AdminResource,
        object_id: str | None,
        actor: Actor | None,
        error_type: str,
        *,
        operation: str | None = None,
    ) -> None:
        await self._event(
            context,
            "failure",
            action,
            resource,
            object_id,
            actor,
            error_type,
            operation,
        )
