"""
MCP server that exposes the 5-agent code repair pipeline as two tools:

  fix_github_issue(url)        — starts the pipeline, returns a job_id immediately
  get_repair_status(job_id)    — polls for the result

This async job pattern avoids MCP client timeouts: the pipeline runs in a
background thread and the client polls until done.

Run with:
    python -m src.mcp_server
"""

import asyncio
import logging
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from src.graph import build_graph
from src.state import initial_state

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)

server = Server("agentic-code-repair")
_executor = ThreadPoolExecutor(max_workers=2)

# job_id → { status, result, started_at, finished_at }
_jobs: dict[str, dict] = {}

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _derive_instance_id(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    owner, repo, number = parts[3], parts[4], parts[6]
    return f"{owner}__{repo}-{number}"


def _fetch_issue_body(issue_url: str) -> str:
    from src.tools.github_tools import _get_repo
    parts = issue_url.rstrip("/").split("/")
    repo_full_name = f"{parts[3]}/{parts[4]}"
    issue_number = int(parts[6])
    repo = _get_repo(repo_full_name)
    issue = repo.get_issue(issue_number)
    return issue.body or ""


def _run_pipeline(job_id: str, issue_url: str, quick_mode: bool) -> None:
    """Runs in a background thread. Writes result into _jobs[job_id]."""
    os.chdir(PROJECT_DIR)
    try:
        issue_body = _fetch_issue_body(issue_url)
        instance_id = _derive_instance_id(issue_url)

        graph = build_graph()
        state = initial_state(
            issue_url=issue_url,
            issue_body=issue_body,
            instance_id=instance_id,
            eval_mode=False,
            quick_mode=quick_mode,
            fail_to_pass=[],
        )

        final = graph.invoke(state)

        _jobs[job_id]["result"] = {
            "instance_id":   instance_id,
            "fix_score":     final.get("fix_score", 0.0),
            "broken_file":   final.get("broken_file", ""),
            "core_problem":  final.get("core_problem", ""),
            "pr_url":        final.get("pr_url", ""),
            "retry_count":   final.get("retry_count", 0),
            "error":         final.get("error"),
            "patch_preview": (final.get("patch") or "")[:500],
        }
        _jobs[job_id]["status"] = "done"

    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["result"] = {"error": str(e)}
        logger.error(f"pipeline failed for job {job_id}: {e}", exc_info=True)
    finally:
        _jobs[job_id]["finished_at"] = datetime.utcnow().isoformat()


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="fix_github_issue",
            description=(
                "Start the 5-agent code repair pipeline on a GitHub issue. "
                "Returns a job_id immediately — the pipeline runs in the background. "
                "Call get_repair_status(job_id) to poll for the result."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "issue_url": {
                        "type": "string",
                        "description": "Full GitHub issue URL, e.g. https://github.com/owner/repo/issues/123",
                    },
                    "quick_mode": {
                        "type": "boolean",
                        "description": "Skip pytest, use LLM semantic scoring only (~30s). Default true.",
                        "default": True,
                    },
                },
                "required": ["issue_url"],
            },
        ),
        types.Tool(
            name="get_repair_status",
            description=(
                "Poll the status of a repair job started by fix_github_issue. "
                "Returns 'running' until done, then the full result."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned by fix_github_issue",
                    }
                },
                "required": ["job_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "fix_github_issue":
        issue_url = arguments.get("issue_url", "").strip()
        if not issue_url:
            raise ValueError("issue_url is required")

        quick_mode = arguments.get("quick_mode", True)
        job_id = str(uuid.uuid4())[:8]

        _jobs[job_id] = {
            "status":     "running",
            "result":     None,
            "started_at": datetime.utcnow().isoformat(),
            "finished_at": None,
            "issue_url":  issue_url,
        }

        loop = asyncio.get_event_loop()
        loop.run_in_executor(_executor, _run_pipeline, job_id, issue_url, quick_mode)

        return [types.TextContent(type="text", text=(
            f"Pipeline started.\n"
            f"job_id     : {job_id}\n"
            f"issue_url  : {issue_url}\n"
            f"quick_mode : {quick_mode}\n\n"
            f"Call get_repair_status(\"{job_id}\") to check progress. "
            f"Poll every 30 seconds — typical runtime is 30–90 seconds."
        ))]

    elif name == "get_repair_status":
        job_id = arguments.get("job_id", "").strip()
        if not job_id:
            raise ValueError("job_id is required")
        if job_id not in _jobs:
            raise ValueError(f"Unknown job_id: {job_id}. Start a job with fix_github_issue first.")

        job = _jobs[job_id]

        if job["status"] == "running":
            elapsed = ""
            if job.get("started_at"):
                from datetime import timezone
                start = datetime.fromisoformat(job["started_at"])
                secs = int((datetime.utcnow() - start).total_seconds())
                elapsed = f" ({secs}s elapsed)"
            return [types.TextContent(type="text", text=(
                f"Status  : running{elapsed}\n"
                f"job_id  : {job_id}\n"
                f"Try again in 30 seconds."
            ))]

        result = job["result"]

        if job["status"] == "error":
            return [types.TextContent(type="text", text=(
                f"Status  : ERROR\n"
                f"job_id  : {job_id}\n"
                f"Error   : {result.get('error', 'unknown')}\n"
            ))]

        approved = result.get("fix_score", 0.0) >= 0.6
        status = "APPROVED" if approved else "NOT APPROVED"

        output = (
            f"Status       : {status}\n"
            f"job_id       : {job_id}\n"
            f"Fix score    : {result['fix_score']:.2f}\n"
            f"Broken file  : {result['broken_file']}\n"
            f"Core problem : {result['core_problem']}\n"
            f"PR URL       : {result['pr_url'] or 'n/a'}\n"
            f"Retries      : {result['retry_count']}\n"
            f"Error        : {result['error'] or 'none'}\n"
            f"Started      : {job['started_at']}\n"
            f"Finished     : {job['finished_at']}\n"
        )

        if result.get("patch_preview"):
            output += f"\nPatch preview:\n{result['patch_preview']}\n"

        return [types.TextContent(type="text", text=output)]

    raise ValueError(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
