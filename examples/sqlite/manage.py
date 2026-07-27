"""Explicit database initialization and role seeding for the SQLite example."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .app import initialize_database, seed_user


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"{name} is required")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init", help="apply the migration to a new database")
    initialize.add_argument("--database", type=Path, required=True)

    seed = commands.add_parser("seed", help="create one user and grant an admin role")
    seed.add_argument("--database", type=Path, required=True)
    seed.add_argument("--origin", required=True)
    seed.add_argument("--email", required=True)
    seed.add_argument("--role", choices=("viewer", "editor", "operator"), required=True)
    seed.add_argument("--password-env", default="EXAMPLE_PASSWORD")

    args = parser.parse_args(argv)
    if args.command == "init":
        initialize_database(args.database)
        return 0

    password = _required_environment(args.password_env)
    auth_secret = _required_environment("AUTH_SECRET")
    asyncio.run(
        seed_user(
            database_path=args.database,
            origin=args.origin,
            auth_secret=auth_secret,
            email=args.email,
            password=password,
            role=args.role,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
