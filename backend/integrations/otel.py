"""OpenTelemetry tracer + auto-instrumentation init.

OneAgent provides container/host metrics + Smartscape, but its
Python deep monitoring in v1.337 doesn't auto-instrument
ASGI/FastAPI request paths. We bridge that gap with the OTel SDK
and a handful of auto-instrumentations that hook FastAPI,
SQLAlchemy, asyncpg, and httpx — covering every Parity in/out
edge that mattered for APM.

Exports via OTLP-HTTP to Dynatrace's OTel ingest endpoint
(``${OTEL_ENDPOINT}/v1/traces``). Auth is a classic API token
with ``openTelemetryTrace.ingest`` scope (PARITY_OTEL_TOKEN, minted
once via the OAuth client and persisted in .env).

Single entry point: call ``init_otel(app)`` from main.py BEFORE
the FastAPI app starts handling requests. Idempotent — safe to
call multiple times during dev reloads.
"""
from __future__ import annotations

import os

import structlog

log = structlog.get_logger()

_INSTALLED = False


def init_otel(app=None) -> bool:
    """Wire OTel SDK + auto-instrumentations. Returns True on success.

    No-ops when ``PARITY_OTEL_DISABLED`` is set or when the OTLP
    endpoint / token aren't configured. The fallback is benign:
    the OneAgent process metrics continue regardless.
    """
    global _INSTALLED
    if _INSTALLED:
        return True
    if os.environ.get("PARITY_OTEL_DISABLED", "").lower() in ("1", "true", "yes"):
        log.info("otel_disabled_via_env")
        return False

    endpoint = (os.environ.get("OTEL_ENDPOINT") or "").rstrip("/")
    token = os.environ.get("PARITY_OTEL_TOKEN") or ""
    if not endpoint or not token:
        log.info("otel_skipped_no_endpoint_or_token")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except Exception as e:
        log.warning("otel_sdk_import_failed", error=str(e))
        return False

    # service.name → what Dynatrace shows in the Services list.
    # `dt.tags` is the Dynatrace convention for tagging entities
    # that come in via OTel ingest — we set "Environment:parity"
    # so the OneAgent APM dashboard's tag filter picks up this
    # service alongside the OneAgent-discovered ones.
    service_name = os.environ.get("OTEL_SERVICE_NAME", "parity-backend")
    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "parity",
        "service.version": os.environ.get("PARITY_VERSION", "0.1.0"),
        "dt.security_context": "parity",
        "dt.tags": "parity,parity-backend,Environment:parity",
    })

    provider = TracerProvider(resource=resource)
    # Dynatrace OTLP path: ${endpoint}/v1/traces (and /v1/metrics, /v1/logs
    # for those signals). Auth: "Api-Token <classic-token>" header.
    exporter = OTLPSpanExporter(
        endpoint=f"{endpoint}/v1/traces",
        headers={"Authorization": f"Api-Token {token}"},
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    # Auto-instrumentations. Each guarded individually so one
    # missing dep doesn't tear down the whole init.
    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
        except Exception as e:
            log.warning("otel_fastapi_instrument_failed", error=str(e))
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()
    except Exception as e:
        log.warning("otel_sqlalchemy_instrument_failed", error=str(e))
    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        AsyncPGInstrumentor().instrument()
    except Exception as e:
        log.warning("otel_asyncpg_instrument_failed", error=str(e))
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except Exception as e:
        log.warning("otel_httpx_instrument_failed", error=str(e))

    log.info(
        "otel_initialised",
        service=service_name,
        endpoint=endpoint,
        token_prefix=token[:14] + "…",
    )
    _INSTALLED = True
    return True
