"""
Langfuse observability shim (compatible with Langfuse v4).

If LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set (non-placeholder),
wraps OpenAI with langfuse.openai so every LLM call is auto-traced.

observe() and langfuse_context are kept as no-ops — v4 removed decorators
in favour of OpenTelemetry. The @observe decorators on agents are harmless.
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
_sk = os.getenv("LANGFUSE_SECRET_KEY", "")
_ENABLED = bool(_pk and _sk and not _pk.startswith("your_") and not _sk.startswith("your_"))

if _ENABLED:
    try:
        from langfuse.openai import OpenAI
        logger.info("Langfuse tracing enabled — LLM calls will be traced automatically")
    except ImportError:
        _ENABLED = False
        logger.warning("langfuse not installed — tracing disabled. Run: pip install langfuse")

if not _ENABLED:
    from openai import OpenAI  # type: ignore[assignment]

# v4 has no decorators module — always no-op
langfuse_context = None


def observe(**_kw):
    def _decorator(fn):
        return fn
    return _decorator
