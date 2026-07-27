# Native Workers + D1 compatibility gate

This gate runs the exact `examples/tasks.py` resource and generated query
facade used by the SQLite example on a real local D1 binding under workerd.
There is no ASGI server, ASGI adapter, WSGI bridge, ORM, or SQL builder.

## Pinned profile

Measured on 2026-07-28:

| Component | Exact profile |
|---|---|
| Cloudflare compatibility date | `2026-07-27` |
| Python Workers SDK | `workers-py==1.15.0` |
| Python runtime SDK | `workers-runtime-sdk==1.6.3` |
| Wrangler / workerd launcher | `wrangler==4.114.0` |
| Node.js | `24` in CI; `24.18.0` for the recorded local run |
| Python Workers interpreter observed by Pywrangler | CPython/Pyodide `3.13.2` |
| Uncompressed upload | `1232.30 KiB` |
| Gzip upload | `281.56 KiB` |

The size includes candidate wheels for Hayate, hayate-admin, hayate-htmx, and
hayate-sql plus Jinja and Workers runtime support. The script rejects ASGI,
AWS, WSGI, package metadata, bytecode, and cache files in the upload.

## Coverage

`scripts/check_workers_d1.sh`:

1. builds all four local candidate wheels and prints SHA-256 hashes;
2. applies the same forward migration and packages the same resource module;
3. verifies unauthenticated, role-denied, and cross-origin rejection;
4. verifies validation and safe HTML escaping;
5. creates, lists, gets, updates, bulk-closes, and deletes through generated
   D1 calls;
6. searches and resolves same-tenant relationships while proving that another
   tenant's choice, label, and object ID are not disclosed;
7. creates, updates, and deletes bounded inline children while rejecting a
   cross-tenant child-ID substitution before storage;
8. verifies a partial bulk result and per-object operation-tagged audit;
9. traverses a composite keyset cursor, applies a saved view, and rejects
   cross-tenant records;
10. downloads a separately authorized, field-allowlisted CSV and proves notes
    and another tenant's row are absent;
11. verifies full-page and htmx fragment representations;
12. reads persistent audit rows and proves that bound/form values are absent;
13. renders separately authorized, paginated object history and repeats the
   non-disclosure assertion on its HTML.

SQLite list count/results share a native transaction. D1 request factories use
a `first-primary` session for sequential consistency. Each inline request
performs one parent/tenant-checked mutation statement; follow-up reads remain
in that session. The local gate preserves D1 state but starts a fresh Worker
process between scenarios because the current Python workerd boundary has a
cumulative POST-body failure that also reproduces in the raw Workers SDK
control.

Run it from the repository root with Node 24 first on `PATH`:

```sh
bash scripts/check_workers_d1.sh
```

The bearer role tokens in this local probe are test identities, not a
production authentication design. In a deployment, the same authorizer should
resolve Cloudflare Access, hayate-auth, or another reviewed identity provider.
