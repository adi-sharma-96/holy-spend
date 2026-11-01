#!/usr/bin/env bash
set -euo pipefail

# Disposable CI PostgreSQL only. Credentials and owner ID are synthetic.
export OWNER_USER_ID=eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee
export PAT_PEPPER=ci-synthetic-current-pepper
export PAT_PEPPER_VERSION=v2
export PAT_PREVIOUS_PEPPER=ci-synthetic-previous-pepper
export PAT_PREVIOUS_PEPPER_VERSION=v1
export PAT_PREVIOUS_PEPPER_RETIRE_AT=2099-01-01T00:00:00+00:00
export DATABASE_URL="$TEST_DATABASE_URL"
export SMOKE_ADMIN_DATABASE_URL="$TEST_ADMIN_DATABASE_URL"

psql "$TEST_ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -q -c \
  "insert into auth.users (id, email) values ('$OWNER_USER_ID', 'ci-smoke@example.test') on conflict (id) do nothing"
psql "$TEST_ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -q -c \
  "insert into profiles (id) values ('$OWNER_USER_ID') on conflict (id) do nothing"

cleanup() {
  kill "$gateway_pid" "$upstream_pid" 2>/dev/null || true
  wait "$gateway_pid" "$upstream_pid" 2>/dev/null || true
  psql "$TEST_ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -q -c \
    "delete from oauth_authorization_codes where user_id = '$OWNER_USER_ID'; \
     delete from oauth_refresh_tokens where user_id = '$OWNER_USER_ID'; \
     delete from personal_access_tokens where user_id = '$OWNER_USER_ID'; \
     delete from auth.users where id = '$OWNER_USER_ID'" || true
}

export MCP_ENABLED=true AUTH_MODE=single_user
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8766 --no-access-log >/dev/null 2>&1 &
upstream_pid=$!
export MCP_ENABLED=false AUTH_MODE=pat MCP_GATEWAY_UPSTREAM_URL=http://127.0.0.1:8766/mcp
export OAUTH_CLIENT_ID=ci-smoke-client
export OAUTH_CLIENT_SECRET=ci-smoke-client-secret
export SMOKE_OAUTH_CLIENT_SECRET="$OAUTH_CLIENT_SECRET"
export OAUTH_ISSUER_URL=http://127.0.0.1:8765
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8765 --no-access-log >/dev/null 2>&1 &
gateway_pid=$!
trap cleanup EXIT

ready=0
for _ in $(seq 1 30); do
  if curl --silent --fail --max-time 1 http://127.0.0.1:8765/health >/dev/null && \
     curl --silent --fail --max-time 1 http://127.0.0.1:8766/health >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo 'Local gateway/upstream readiness failed' >&2
  exit 1
fi

assert_exact_cleanup() {
  SMOKE_RESULT_JSON="$1" python - <<'PY'
import json
import os
import psycopg

result = json.loads(os.environ["SMOKE_RESULT_JSON"])
assert result["success"] and result["stages"]["cleanup"] == "PASSED"
with psycopg.connect(os.environ["SMOKE_ADMIN_DATABASE_URL"]) as conn:
    for key, table in (
        ("pat_id", "personal_access_tokens"),
        ("oauth_pat_id", "personal_access_tokens"),
        ("refresh_id", "oauth_refresh_tokens"),
    ):
        row = conn.execute(
            f"select revoked_at from {table} where id = %s and user_id = %s",
            (result["created_ids"][key], os.environ["OWNER_USER_ID"]),
        ).fetchone()
        assert row is not None and row[0] is not None, key
PY
}

current_result=$(python -m scripts.auth_smoke \
  --base-url http://127.0.0.1:8765 --allow-loopback-http \
  --user-id "$OWNER_USER_ID" \
  --oauth-client-id "$OAUTH_CLIENT_ID" \
  --oauth-redirect-uri https://claude.ai/api/mcp/auth_callback)
printf '%s\n' "$current_result"
assert_exact_cleanup "$current_result"

# Model a pre-rotation CLI talking to a dual-key gateway. Its new PAT hashes
# with the old pepper; OAuth tokens still mint with the gateway's new pepper.
previous_result=$(env -u PAT_PREVIOUS_PEPPER -u PAT_PREVIOUS_PEPPER_VERSION -u PAT_PREVIOUS_PEPPER_RETIRE_AT \
  PAT_PEPPER=ci-synthetic-previous-pepper PAT_PEPPER_VERSION=v1 \
  python -m scripts.auth_smoke \
    --base-url http://127.0.0.1:8765 --allow-loopback-http \
    --user-id "$OWNER_USER_ID" \
    --oauth-client-id "$OAUTH_CLIENT_ID" \
    --oauth-redirect-uri https://claude.ai/api/mcp/auth_callback)
printf '%s\n' "$previous_result"
assert_exact_cleanup "$previous_result"
