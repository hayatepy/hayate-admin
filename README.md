# hayate-admin

Secure operational administration for [Hayate](https://github.com/hayatepy/hayate),
using explicit resources and checked SQL rather than ORM or database reflection.

The project is being built in public. The first implementation milestone is
tracked in [issue #1](https://github.com/hayatepy/hayate-admin/issues/1), with
SQLite/hayate-sql and Workers/D1 executable evidence in
[issues #2](https://github.com/hayatepy/hayate-admin/issues/2) and
[#3](https://github.com/hayatepy/hayate-admin/issues/3).

Design principles:

- fail-closed, application-injected authentication and authorization;
- no anonymous or default-superuser mode;
- explicit typed fields and repository operations;
- search, filters, sort, and pagination as allowlisted values, never SQL text;
- same-origin mutation protection and safely escaped output;
- audit events without submitted field values;
- ordinary Hayate routes that work without ASGI on supported edge runtimes.

This is an internal management tool, not a public application UI or an ORM.

## License

MIT
