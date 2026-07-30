# Releasing hayate-admin

The release workflow first proves the package against native Workers/D1. It
then verifies version consistency, runs the full test and dependency-audit
gates, builds wheel and source archives, generates an SPDX JSON SBOM, and
attests both artifacts and SBOM through GitHub's OIDC provenance. Publishing
uses PyPI Trusted Publishing; no long-lived PyPI token is stored.

## One-time repository setup

Configure a PyPI pending publisher or project publisher with:

- owner: `hayatepy`
- repository: `hayate-admin`
- workflow: `release.yml`
- environment: `pypi`

Protect the `pypi` environment with a `v*` tag policy and enable GitHub private
vulnerability reporting.

The first public releases have an immutable dependency order:

1. verify `hayate-htmx==0.2.0` from the public index;
2. rerun the existing signed `hayate-admin` `v0.2.0` workflow after saving the
   pending publisher;
3. verify `hayate-admin==0.2.0` from the public index;
4. create signed `v0.3.0` only from the reviewed current main commit.

Never move `v0.2.0`, and never create `v0.3.0` before the first public project
exists.

## Release checklist

1. Confirm `CHANGELOG.md` describes the release.
2. Confirm `pyproject.toml`, `hayate_admin.__version__`, and `uv.lock` all
   contain the intended version.
3. Run:

   ```sh
   uv sync --locked
   uv run ruff check src examples tests typing_tests
   uv run ruff format --check src examples tests typing_tests
   uv run mypy src examples typing_tests
   uv run pytest -q
   npm ci --ignore-scripts
   HAYATE_ADMIN_BROWSER_TESTS=1 uv run pytest \
     tests/browser/test_sqlite_admin.py -q
   uv build
   uv run python scripts/check_dist.py
   uv run --with pip-audit==2.10.0 pip-audit
   uvx zizmor==1.28.0 .github/workflows
   ```

4. Run the native Workers/D1 gate from the release workflow.
5. Merge only with all blocking GitHub checks green.
6. Create and push an annotated `v<version>` tag from the reviewed merge
   commit. Do not move or reuse a published tag.
7. Verify the release workflow's PyPI publish, attestations, SPDX SBOM, and
   GitHub release assets.
8. Install the wheel from PyPI into a clean environment and run the README
   example.

The workflow refuses a tag whose name differs from the package version.
