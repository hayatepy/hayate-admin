# Changelog

All notable changes to hayate-admin are documented here.

## [Unreleased]

### Added

- Add fail-closed typed resource, field, repository, authorization, and audit
  contracts.
- Add safely escaped progressive CRUD routes with bounded search, filters,
  sorting, pagination, and form parsing.
- Add exact-Origin and Fetch-Metadata mutation protection, accessible
  validation errors, redacted operation events, restrictive response headers,
  and full-page/htmx fragment selection.
- Add an executable SQLite reference using hayate-auth sessions, separately
  provisioned roles, generated hayate-sql CRUD, persistent redacted audit
  events, and a real Chromium flow.
- Add request-scoped repository and audit factories plus a pinned native
  Workers/D1 gate that reuses the same resource and generated query facade
  without ASGI.
- Add explicit bounded bulk actions with resource and per-object authorization,
  complete partial-result contracts, accessible controls, and operation-tagged
  redacted audit evidence on SQLite, Chromium, and native D1.
- Add separately authorized, bounded object history through an explicit
  request-local reader contract and the same generated SQLite/D1 audit queries.
- Add explicit searchable to-one relationships with tenant-scoped search and
  single-ID resolution callbacks, per-target authorization, preloaded display
  fields, and accessible full-page/htmx choice flows.
- Add bounded reverse inline create/update/delete with complete child
  snapshots, per-record authorization, redacted audit events, and
  repository-owned atomic parent/tenant checks.
- Exercise the same relationship and inline definitions with checked generated
  SQL on SQLite and native Workers/D1, including cross-tenant ID-substitution
  rejection and a real Chromium flow.
