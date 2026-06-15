"""
Langfuse observability shim.

If LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set (and not placeholder
values), wraps OpenAI with Langfuse's drop-in client and exposes the
@observe decorator for function-level tracing.

Otherwise falls back to the plain openai.OpenAI and a no-op observe().
"""
import os
import logging

logger = logging.getLogger(__name__)

_pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
_sk = os.getenv("LANGFUSE_SECRET_KEY", "")
_ENABLED = bool(_pk and _sk and not _pk.startswith("your_") and not _sk.startswith("your_"))

if _ENABLED:
    try:
        from langfuse.openai import OpenAI
        from langfuse.decorators import observe, langfuse_context
        logger.info("Langfuse tracing enabled (host=%s)", os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))
    except ImportError:
        _ENABLED = False
        logger.warning("langfuse not installed — tracing disabled. Run: pip install langfuse")

if not _ENABLED:
    from openai import OpenAI  # type: ignore[assignment]
    langfuse_context = None

    def observe(**_kw):
        def _decorator(fn):
            return fn
        return _decorator
