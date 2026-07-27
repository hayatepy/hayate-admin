#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ecosystem_dir="$(dirname "${repo_dir}")"
hayate_source_dir="${HAYATE_SOURCE_DIR:-${ecosystem_dir}/hayate}"
htmx_source_dir="${HAYATE_HTMX_SOURCE_DIR:-${ecosystem_dir}/hayate-htmx}"
sql_source_dir="${HAYATE_SQL_SOURCE_DIR:-${ecosystem_dir}/hayate-sql}"
test_dir="$(mktemp -d)"
wheels_dir="${test_dir}/wheels"
bundle_dir="${test_dir}/bundle"
log_file="${test_dir}/workerd.log"
dry_run_log="${test_dir}/dry-run.log"
body_file="${test_dir}/body"
headers_file="${test_dir}/headers"
port=8796
origin="http://127.0.0.1:${port}"
server_pid=""

terminate_tree() {
  local parent_pid="$1"
  local child_pid
  while read -r child_pid; do
    if [[ -n "${child_pid}" ]]; then
      terminate_tree "${child_pid}"
    fi
  done < <(pgrep -P "${parent_pid}" 2>/dev/null || true)
  kill "${parent_pid}" 2>/dev/null || true
}

stop_worker() {
  if [[ -n "${server_pid}" ]] && kill -0 "${server_pid}" 2>/dev/null; then
    terminate_tree "${server_pid}"
    wait "${server_pid}" 2>/dev/null || true
  fi
  server_pid=""
}

start_worker() {
  local ready=false
  (
    cd "${test_dir}"
    uvx --from workers-py==1.15.0 pywrangler dev --port "${port}"
  ) >"${log_file}" 2>&1 &
  server_pid=$!

  for _ in {1..60}; do
    if curl --fail --silent --max-time 2 "${origin}/" >"${body_file}"; then
      ready=true
      break
    fi
    if ! kill -0 "${server_pid}" 2>/dev/null; then
      cat "${log_file}"
      exit 1
    fi
    sleep 1
  done
  if [[ "${ready}" != true ]]; then
    cat "${log_file}"
    exit 1
  fi
}

restart_worker() {
  stop_worker
  start_worker
}

cleanup() {
  stop_worker
}
trap cleanup EXIT

node_major="$(node -p 'process.versions.node.split(".")[0]')"
if [[ "${node_major}" != "24" ]]; then
  echo "Node.js 24 is required; found $(node --version)." >&2
  exit 2
fi

mkdir -p "${wheels_dir}"
(
  cd "${repo_dir}"
  uv build --wheel --out-dir "${wheels_dir}"
)
for source_dir in \
  "${hayate_source_dir}" \
  "${htmx_source_dir}" \
  "${sql_source_dir}"; do
  if [[ ! -f "${source_dir}/pyproject.toml" ]]; then
    echo "Candidate package source is missing: ${source_dir}" >&2
    exit 2
  fi
  (
    cd "${source_dir}"
    uv build --wheel --out-dir "${wheels_dir}"
  )
done

admin_wheel="$(find "${wheels_dir}" -maxdepth 1 -name 'hayate_admin-*.whl' -print -quit)"
hayate_wheel="$(find "${wheels_dir}" -maxdepth 1 -name 'hayate-*.whl' ! -name 'hayate_admin-*' ! -name 'hayate_htmx-*' -print -quit)"
htmx_wheel="$(find "${wheels_dir}" -maxdepth 1 -name 'hayate_htmx-*.whl' -print -quit)"
sql_wheel="$(find "${wheels_dir}" -maxdepth 1 -name 'hayate_sql-*.whl' -print -quit)"
for wheel in "${admin_wheel}" "${hayate_wheel}" "${htmx_wheel}" "${sql_wheel}"; do
  test -f "${wheel}"
  shasum -a 256 "${wheel}"
done

mkdir -p "${test_dir}/examples/sqlite/migrations" "${test_dir}/examples/workers_d1"
cp "${repo_dir}/examples/tasks.py" "${test_dir}/examples/workers_d1/tasks.py"
cp "${repo_dir}/examples/sqlite/generated_queries.py" \
  "${test_dir}/examples/workers_d1/generated_queries.py"
cp "${repo_dir}/examples/sqlite/migrations/0001_create_tasks.sql" \
  "${test_dir}/examples/sqlite/migrations/0001_create_tasks.sql"
cp "${repo_dir}/examples/workers_d1/entry.py" \
  "${test_dir}/examples/workers_d1/entry.py"
cp "${repo_dir}/examples/workers_d1/wrangler.toml" "${test_dir}/wrangler.toml"
cp "${repo_dir}/examples/workers_d1/package.json" "${test_dir}/package.json"
sed \
  -e "s|\"hayate==0.13.0\"|\"hayate @ file://${hayate_wheel}\"|" \
  -e "s|\"hayate-admin==0.2.0\"|\"hayate-admin @ file://${admin_wheel}\"|" \
  -e "s|\"hayate-htmx==0.2.0\"|\"hayate-htmx @ file://${htmx_wheel}\"|" \
  -e "s|\"hayate-sql==0.1.1\"|\"hayate-sql @ file://${sql_wheel}\"|" \
  "${repo_dir}/examples/workers_d1/pyproject.toml" >"${test_dir}/pyproject.toml"

(
  cd "${test_dir}"
  npm install --no-audit --no-fund
  echo "runtime[node]=$(node --version)"
  echo "runtime[wrangler]=$(./node_modules/.bin/wrangler --version | tail -1)"
  echo "runtime[pywrangler]=$(uvx --from workers-py==1.15.0 pywrangler --version)"
  uvx --from workers-py==1.15.0 pywrangler sync
  uvx --from workers-py==1.15.0 pywrangler d1 migrations apply DB \
    --local \
    --config wrangler.toml
  uvx --from workers-py==1.15.0 pywrangler deploy \
    --dry-run \
    --outdir "${bundle_dir}"
) >"${dry_run_log}" 2>&1

upload_size="$(grep -F "Total Upload:" "${dry_run_log}" | tail -1)"
if [[ -z "${upload_size}" ]]; then
  cat "${dry_run_log}"
  echo "Wrangler dry-run did not report an upload size." >&2
  exit 1
fi
echo "upload[admin-d1]=${upload_size}"

for excluded_path in \
  "python_modules/asgi.py" \
  "python_modules/hayate/adapters/asgi.py" \
  "python_modules/hayate/adapters/aws.py" \
  "python_modules/workers/wsgi.py"; do
  if [[ -e "${bundle_dir}/${excluded_path}" ]]; then
    echo "excluded path reached Wrangler upload: ${excluded_path}" >&2
    exit 1
  fi
done
if find "${bundle_dir}" -type d -name "*.dist-info" -print -quit | grep -q .; then
  echo "package metadata reached Wrangler upload" >&2
  exit 1
fi
if find "${bundle_dir}" \( -type f -name "*.pyc" -o -type d -name "__pycache__" \) \
  -print -quit | grep -q .; then
  echo "Python cache reached Wrangler upload" >&2
  exit 1
fi

start_worker
python - "${body_file}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
assert payload == {
    "runtime": "cloudflare-python-workers",
    "storage": "d1",
    "asgi": False,
}
PY

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    "${origin}/admin/tasks"
)"
test "${status}" = "403"

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H 'Origin: https://evil.example' \
    -H 'Sec-Fetch-Site: cross-site' \
    --data-urlencode 'name=Cross site' \
    --data-urlencode 'status=open' \
    --data-urlencode 'notes=rejected' \
    "${origin}/admin/tasks/create"
)"
test "${status}" = "403"

# Current local Python workerd has a cumulative POST-body failure that also
# reproduces in the raw Workers SDK control. Keep D1 state, but isolate each
# compatibility scenario in a fresh Worker process.
restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer viewer' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'name=Denied viewer write' \
    --data-urlencode 'status=open' \
    --data-urlencode 'notes=rejected' \
    "${origin}/admin/tasks/create"
)"
test "${status}" = "403"

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data 'name=&status=open&notes=validation-secret' \
    "${origin}/admin/tasks/create"
)"
test "${status}" = "422"
grep -Fq "This field is required." "${body_file}"

status="$(
  curl --silent --dump-header "${headers_file}" --output "${body_file}" \
    --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'name=<script>d1-sentinel</script>' \
    --data-urlencode 'status=open' \
    --data-urlencode 'active=true' \
    --data-urlencode 'notes=d1-bound-secret' \
    "${origin}/admin/tasks/create"
)"
test "${status}" = "303"
grep -Eiq '^location: /admin/tasks/object/1' "${headers_file}"

restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'action=close' \
    --data-urlencode 'selected=1' \
    --data-urlencode 'selected=missing' \
    "${origin}/admin/tasks/bulk"
)"
test "${status}" = "200"
grep -Fq "1 completed; 1 failed." "${body_file}"

status="$(
  curl --silent --dump-header "${headers_file}" --output "${body_file}" \
    --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'name=Alpha task' \
    --data-urlencode 'status=closed' \
    --data-urlencode 'notes=second-bound-secret' \
    "${origin}/admin/tasks/create"
)"
test "${status}" = "303"

restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks?sort=name&direction=asc"
)"
test "${status}" = "200"
grep -Fiq '<!doctype html>' "${body_file}"
grep -Fq '&lt;script&gt;d1-sentinel&lt;/script&gt;' "${body_file}"
if grep -Fq '<script>d1-sentinel</script>' "${body_file}"; then
  echo "unescaped record value reached D1 admin HTML" >&2
  exit 1
fi

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks/object/1"
)"
test "${status}" = "200"

restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'name=Updated D1 task' \
    --data-urlencode 'status=closed' \
    --data-urlencode 'notes=update-bound-secret' \
    "${origin}/admin/tasks/object/1/edit"
)"
test "${status}" = "303"

restart_worker

status="$(
  curl --silent --dump-header "${headers_file}" --output "${body_file}" \
    --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator:beta' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'name=Beta tenant task' \
    --data-urlencode 'status=open' \
    --data-urlencode 'notes=beta-tenant-secret' \
    "${origin}/admin/tasks/create"
)"
test "${status}" = "303"
grep -Eiq '^location: /admin/tasks/object/3' "${headers_file}"

restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks/relationship/parent_id/choices?q=Beta"
)"
test "${status}" = "200"
grep -Fq "No authorized related records found." "${body_file}"
if grep -Fq "Beta tenant task" "${body_file}"; then
  echo "cross-tenant relationship choice reached alpha HTML" >&2
  exit 1
fi

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator:beta' \
    "${origin}/admin/tasks/relationship/parent_id/choices?q=Beta"
)"
test "${status}" = "200"
grep -Fq "Beta tenant task" "${body_file}"

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks/object/3"
)"
test "${status}" = "404"

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'name=Cross tenant relationship' \
    --data-urlencode 'parent_id=3' \
    --data-urlencode 'status=open' \
    --data-urlencode 'notes=relationship-substitution-secret' \
    "${origin}/admin/tasks/create"
)"
test "${status}" = "422"
grep -Fq "Select an authorized related record." "${body_file}"
if grep -Fq "Beta tenant task" "${body_file}"; then
  echo "cross-tenant relationship label reached validation HTML" >&2
  exit 1
fi

restart_worker

status="$(
  curl --silent --dump-header "${headers_file}" --output "${body_file}" \
    --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'name=Relationship child' \
    --data-urlencode 'parent_id=1' \
    --data-urlencode 'status=open' \
    --data-urlencode 'active=true' \
    --data-urlencode 'notes=relationship-child-secret' \
    "${origin}/admin/tasks/create"
)"
test "${status}" = "303"
grep -Eiq '^location: /admin/tasks/object/4' "${headers_file}"

restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks/object/4"
)"
test "${status}" = "200"
grep -Fq "Updated D1 task" "${body_file}"

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks?sort=name&direction=asc"
)"
test "${status}" = "200"
next_path="$(
  python - "${body_file}" <<'PY'
import html
import re
import sys
from pathlib import Path

body = html.unescape(Path(sys.argv[1]).read_text())
match = re.search(r'href="([^"]+\?[^"]*cursor=[^"]+)"[^>]*>Next</a>', body)
assert match is not None, body
print(match.group(1))
PY
)"
status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}${next_path}"
)"
test "${status}" = "200"
grep -Fq "Updated D1 task" "${body_file}"
grep -Fq ">First</a>" "${body_file}"

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks?view=closed-by-name"
)"
test "${status}" = "200"
grep -Fq "Alpha task" "${body_file}"
grep -Fq "Updated D1 task" "${body_file}"
grep -Fq 'aria-current="page"' "${body_file}"

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer viewer' \
    "${origin}/admin/tasks/export.csv"
)"
test "${status}" = "403"

status="$(
  curl --silent --dump-header "${headers_file}" --output "${body_file}" \
    --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks/export.csv?sort=name&direction=asc"
)"
test "${status}" = "200"
grep -Eiq '^content-type: text/csv; charset=utf-8' "${headers_file}"
grep -Eiq '^content-disposition: attachment; filename="tasks.csv"' "${headers_file}"
grep -Fq "ID,Name,Status,Active,Parent task" "${body_file}"
grep -Fq "Updated D1 task" "${body_file}"
grep -Fq "Relationship child" "${body_file}"
if grep -Fq "Beta tenant task" "${body_file}" \
  || grep -Fq "update-bound-secret" "${body_file}" \
  || grep -Fq "relationship-child-secret" "${body_file}"; then
  echo "cross-tenant or non-export field reached D1 CSV" >&2
  exit 1
fi

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks/object/1/inline/subtasks"
)"
test "${status}" = "200"
grep -Fq "Relationship child" "${body_file}"

status="$(
  curl --silent --dump-header "${headers_file}" --output "${body_file}" \
    --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'operation=create' \
    --data-urlencode 'name=Inline D1 child' \
    --data-urlencode 'status=open' \
    --data-urlencode 'active=true' \
    --data-urlencode 'notes=inline-create-secret' \
    "${origin}/admin/tasks/object/1/inline/subtasks"
)"
test "${status}" = "303"
grep -Eiq '^location: /admin/tasks/object/1/inline/subtasks' "${headers_file}"

restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'operation=update' \
    --data-urlencode 'object_id=3' \
    --data-urlencode 'name=Stolen beta task' \
    --data-urlencode 'status=open' \
    --data-urlencode 'active=true' \
    --data-urlencode 'notes=inline-substitution-secret' \
    "${origin}/admin/tasks/object/1/inline/subtasks"
)"
test "${status}" = "422"
grep -Fq "does not belong to this parent" "${body_file}"
if grep -Fq "Beta tenant task" "${body_file}"; then
  echo "cross-tenant inline record reached alpha HTML" >&2
  exit 1
fi

restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'operation=update' \
    --data-urlencode 'object_id=5' \
    --data-urlencode 'name=Updated inline D1 child' \
    --data-urlencode 'status=closed' \
    --data-urlencode 'active=true' \
    --data-urlencode 'notes=inline-update-secret' \
    "${origin}/admin/tasks/object/1/inline/subtasks"
)"
test "${status}" = "303"

restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'operation=delete' \
    --data-urlencode 'object_id=5' \
    "${origin}/admin/tasks/object/1/inline/subtasks"
)"
test "${status}" = "303"

restart_worker

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data-urlencode 'operation=delete' \
    --data-urlencode 'object_id=4' \
    "${origin}/admin/tasks/object/1/inline/subtasks"
)"
test "${status}" = "303"

restart_worker

status="$(
  curl --silent --dump-header "${headers_file}" --output "${body_file}" \
    --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H 'HX-Request: true' \
    "${origin}/admin/tasks?filter_status=closed"
)"
test "${status}" = "200"
grep -Fq '<main id="hayate-admin"' "${body_file}"
grep -Eiq '^vary: .*HX-Request' "${headers_file}"
if grep -Fiq '<!doctype html>' "${body_file}"; then
  echo "htmx request returned a full page" >&2
  exit 1
fi

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    -H "Origin: ${origin}" \
    -H 'Sec-Fetch-Site: same-origin' \
    --data '' \
    "${origin}/admin/tasks/object/2/delete"
)"
test "${status}" = "303"

restart_worker

curl --fail --silent --max-time 5 \
  -H 'Authorization: Bearer operator' \
  "${origin}/probe/audit" >"${body_file}"
python - "${body_file}" <<'PY'
import json
import sys
from pathlib import Path

events = json.loads(Path(sys.argv[1]).read_text())
assert len(events) == 34, events
assert [event["phase"] for event in events].count("success") == 12
assert any(event["error_type"] == "CrossSiteRequest" for event in events)
assert any(event["error_type"] == "AuthorizationDenied" for event in events)
assert any(event["error_type"] == "ValidationError" for event in events)
assert any(event["error_type"] == "InvalidInlineForm" for event in events)
assert sum(event["operation"] == "close" for event in events) == 4
assert sum(event["action"] == "resource:export" for event in events) == 3
assert any(
    event["operation"] == "close"
    and event["object_id"] == "missing"
    and event["error_type"] == "BulkActionFailed"
    for event in events
)
serialized = json.dumps(events, sort_keys=True)
for forbidden in (
    "d1-sentinel",
    "d1-bound-secret",
    "second-bound-secret",
    "update-bound-secret",
    "validation-secret",
    "Denied viewer write",
    "beta-tenant-secret",
    "relationship-substitution-secret",
    "relationship-child-secret",
    "inline-create-secret",
    "inline-substitution-secret",
    "inline-update-secret",
    "Stolen beta task",
):
    assert forbidden not in serialized
for event in events:
    assert set(event) == {
        "id",
        "occurred_at",
        "phase",
        "action",
        "operation",
        "resource",
        "object_id",
        "actor_id",
        "error_type",
    }
print(
    "workerd D1 admin: authorization origin validation escaping CRUD bulk "
    "relationships inlines saved-views cursor CSV htmx audit"
)
PY

status="$(
  curl --silent --output "${body_file}" --write-out '%{http_code}' \
    -H 'Authorization: Bearer operator' \
    "${origin}/admin/tasks/object/1/history"
)"
test "${status}" = "200"
grep -Fq "History for 1" "${body_file}"
grep -Fq "resource:bulk / close" "${body_file}"
if grep -Fq "d1-bound-secret" "${body_file}"; then
  echo "submitted value reached D1 object history" >&2
  exit 1
fi
echo "workerd D1 admin history: authorized paginated redacted object events"
