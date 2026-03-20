import logging

logger = logging.getLogger("interview-prep-agents")


def patch_opentelemetry_detach() -> None:
    """Suppress only benign cross-context detach errors from workflow stream teardown."""
    try:
        from opentelemetry import context as otel_context
        from opentelemetry import trace as otel_trace
    except Exception:
        return

    current_detach = getattr(otel_context, "detach", None)
    runtime_context = getattr(otel_context, "_RUNTIME_CONTEXT", None)
    if current_detach is None or runtime_context is None:
        return
    if getattr(current_detach, "_interview_simulator_patched", False):
        return

    def safe_detach(token: object) -> None:
        try:
            runtime_context.detach(token)
        except ValueError as exc:
            if "different Context" in str(exc):
                return
            logger.debug("detach failed: %s", exc)
        except Exception:
            logger.debug("detach failed", exc_info=True)

    setattr(safe_detach, "_interview_simulator_patched", True)
    otel_context.detach = safe_detach
    trace_context_api = getattr(otel_trace, "__dict__", {}).get("context_api")
    if trace_context_api is not None and getattr(trace_context_api, "detach", None) is not None:
        trace_context_api.detach = safe_detach
