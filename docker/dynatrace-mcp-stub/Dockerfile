FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Dynatrace OneAgent codemodule ─────────────────────────────
# See docker/Dockerfile.backend for the full rationale; same
# pattern, same build args (passed from compose).
ARG DT_API_URL
ARG DT_PAAS_TOKEN
RUN if [ -n "${DT_API_URL}" ] && [ -n "${DT_PAAS_TOKEN}" ]; then \
        mkdir -p /opt/dynatrace/oneagent && \
        curl -fsSL -o /tmp/oneagent.zip \
            "${DT_API_URL}/v1/deployment/installer/agent/unix/paas/latest?flavor=default&include=python&include=process&Api-Token=${DT_PAAS_TOKEN}" && \
        unzip -q /tmp/oneagent.zip -d /opt/dynatrace/oneagent && \
        rm /tmp/oneagent.zip; \
    fi

RUN pip install --no-cache-dir 'mcp[cli]>=1.0' httpx

COPY server.py .

EXPOSE 8000

CMD ["python", "server.py"]
