# Real Dynatrace MCP server — the official @dynatrace-oss package
# running in HTTP mode so the Python backend can reach it via the
# in-stack streamable-HTTP transport, identical to how it speaks to
# the stub. Requires DT_ENVIRONMENT + DT_PLATFORM_TOKEN at runtime.
FROM node:22-alpine

# Need glibc tooling for OneAgent codemodule install (it's a glibc
# binary); Alpine ships musl, so we use the OneAgent codemodule's
# musl-compatible flavor by requesting include=musl in the installer
# URL below. Also need curl + unzip for the download.
RUN apk add --no-cache curl unzip ca-certificates bash

# ── Dynatrace OneAgent codemodule ─────────────────────────────
# include=nodejs gives us Node auto-instrumentation. The musl flavor
# is needed because this is an Alpine (musl) base image.
ARG DT_API_URL
ARG DT_PAAS_TOKEN
RUN if [ -n "${DT_API_URL}" ] && [ -n "${DT_PAAS_TOKEN}" ]; then \
        mkdir -p /opt/dynatrace/oneagent && \
        curl -fsSL -o /tmp/oneagent.zip \
            "${DT_API_URL}/v1/deployment/installer/agent/unix/paas/latest?flavor=musl&include=nodejs&include=process&Api-Token=${DT_PAAS_TOKEN}" && \
        unzip -q /tmp/oneagent.zip -d /opt/dynatrace/oneagent && \
        rm /tmp/oneagent.zip && \
        echo "OneAgent codemodule installed (musl/node)"; \
    fi

ENV DT_MCP_DISABLE_TELEMETRY=true
RUN npm install -g @dynatrace-oss/dynatrace-mcp-server@1.8.5

EXPOSE 3000

# --host 0.0.0.0 so Docker can reach it; --http picks the
# StreamableHTTPServerTransport instead of stdio.
CMD ["mcp-server-dynatrace", "--http", "--host", "0.0.0.0", "--port", "3000"]

# Lightweight healthcheck — the streamable-HTTP transport responds to
# POST {} with a JSON-RPC error envelope, which is enough to know the
# server is up. 405/400 means the server is processing requests; only
# a connection refusal counts as unhealthy.
HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
  CMD wget -qO- --post-data='{}' --header='Content-Type: application/json' \
      http://127.0.0.1:3000/ 2>&1 | grep -qE 'jsonrpc|error|tools' || exit 1
