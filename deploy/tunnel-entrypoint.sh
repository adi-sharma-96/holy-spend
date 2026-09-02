#!/bin/sh
set -eu

: "${CONTROL_PLANE_API_KEY:?CONTROL_PLANE_API_KEY is required}"
: "${CONTROL_PLANE_TUNNEL_ID:?CONTROL_PLANE_TUNNEL_ID is required}"
: "${MCP_SERVER_URL:?MCP_SERVER_URL is required}"

export HEALTH_LISTEN_ADDR="${HEALTH_LISTEN_ADDR:-0.0.0.0:${PORT:-8080}}"

exec tunnel-client run \
    --log.level="${LOG_LEVEL:-info}" \
    --log.format="${LOG_FORMAT:-json}"
