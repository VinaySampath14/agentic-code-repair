"""
Local MCP server wrapping GitHub API tools used by the planner and PR agent.
Exposes: search_codebase, create_pr

This server is consumed by github_tools.py via the MCP client protocol.
In production, drop-in replacement with the official GitHub MCP server
(github/github-mcp-server) — no changes needed in the consumer.

Run standalone:
    python -m src.github_mcp_server
"""

import asyncio
import json
import logging
import sys

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from src.config import GITHUB_TOKEN
from src.tools.github_tools import _get_repo

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)

server = Server("github-tools")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_codebase",
            description="Search for files in a GitHub repo matching a query string.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_full_name": {"type": "string", "description": "owner/repo"},
                    "query":          {"type": "string", "description": "Search query"},
                },
                "required": ["repo_full_name", "query"],
            },
        ),
        types.Tool(
            name="create_pr",
            description="Open a draft pull request on a GitHub repo.",
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_full_name": {"type": "string", "description": "owner/repo"},
                    "title":          {"type": "string"},
                    "body":           {"type": "string"},
                    "head":           {"type": "string", "description": "source branch"},
                    "base":           {"type": "string", "description": "target branch (default: repo default branch)"},
                },
                "required": ["repo_full_name", "title", "body", "head"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "search_codebase":
        from github import Github, GithubException
        import time

        repo_full_name = arguments["repo_full_name"]
        query = arguments["query"]
        client = Github(GITHUB_TOKEN) if GITHUB_TOKEN else Github()

        for attempt in range(3):
            try:
                results = client.search_code(f"{query} repo:{repo_full_name}")
                paths = [item.path for item in results]
                return [types.TextContent(type="text", text=json.dumps(paths))]
            except GithubException as e:
                if e.status == 403 and attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    return [types.TextContent(type="text", text="[]")]

    elif name == "create_pr":
        from github import GithubException
        import time

        repo_full_name = arguments["repo_full_name"]
        title = arguments["title"]
        body  = arguments["body"]
        head  = arguments["head"]
        base  = arguments.get("base")

        repo = _get_repo(repo_full_name)
        base = base or repo.default_branch

        for attempt in range(3):
            try:
                pr = repo.create_pull(title=title, body=body, head=head, base=base, draft=True)
                return [types.TextContent(type="text", text=pr.html_url)]
            except GithubException as e:
                if e.status == 403 and attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise

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
