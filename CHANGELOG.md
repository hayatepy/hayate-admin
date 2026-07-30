# Changelog

All notable changes to hayate-admin are documented here.

## [Unreleased]

### Changed

- Route package discovery, start, and tested-compatibility links through
  `hayatepy.dev`, including the future PyPI project homepage.

## [0.3.0] - 2026-07-30

### Added

- Add immutable per-site message catalogs with English defaults, validated
  locale tags and placeholders, localized navigation/forms/validation/history/
  bulk/relationship/empty/error states, and no ambient locale mutation.
- Add escaped plain-text branding plus contrast-checked color and density
  tokens, rendered through a deterministic stylesheet authorized by an exact
  CSP hash.
- Add semantic landmarks, skip navigation, visible keyboard focus,
  reduced-motion handling, and a pinned axe-core Chromium gate across real
  CRUD, bulk, history, relationship, inline, saved-view, and delete flows.

## [0.2.0] - 2026-07-28

### Added

- Add static saved views composed only from declared search, filter, and sort
  controls.
- Add opt-in forward keyset pagination with query-bound opaque cursor envelopes
  and repository-owned continuations.
- Add separately authorized CSV exports with explicit callbacks and field
  allowlists, per-object authorization, formula-safe cells, row/byte limits,
  download hardening, and redacted audit evidence.
- Exercise saved views, cursor traversal, and CSV download with the same
  checked SQL on SQLite, Chromium, and native Workers/D1.

## [0.1.0] - 2026-07-27

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
