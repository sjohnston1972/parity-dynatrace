# Real Dynatrace MCP server — the official @dynatrace-oss package
# running in HTTP mode so the Python backend can reach it via the
# in-stack streamable-HTTP transport, identical to how it speaks to
# the stub. Requires DT_ENVIRONMENT + DT_PLATFORM_TOKEN at runtime.
FROM node:22-alpine

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
