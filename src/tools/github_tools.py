import asyncio
import json
import os
import sys
import time
import base64
import logging
from github import Github, GithubException, BadCredentialsException
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from mcp import StdioServerParameters
from src.config import GITHUB_TOKEN

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)
_client = Github(GITHUB_TOKEN) if GITHUB_TOKEN else Github()
_anon_client = Github()  # fallback for public repos when token is invalid
_repo_cache: dict = {}


def _get_repo(repo_full_name: str):
    if repo_full_name in _repo_cache:
        return _repo_cache[repo_full_name]
    for client in (_client, _anon_client):
        for attempt in range(3):
            try:
                repo = client.get_repo(repo_full_name)
                _repo_cache[repo_full_name] = repo
                return repo
            except BadCredentialsException:
                logger.warning("GitHub token invalid — retrying with anonymous access")
                break  # try anon_client
            except GithubException as e:
                if e.status == 403 and attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    raise
    raise RuntimeError(f"Could not access repo {repo_full_name} with or without credentials")


def _default_branch(repo_full_name: str) -> str:
    repo = _get_repo(repo_full_name)
    branch = repo.default_branch
    logger.debug(f"default branch for {repo_full_name}: {branch}")
    return branch


def read_file(repo_full_name: str, path: str, ref: str = None) -> str:
    repo = _get_repo(repo_full_name)
    ref = ref or repo.default_branch
    logger.debug(f"read_file: {repo_full_name}/{path}@{ref}")
    for attempt in range(3):
        try:
            content = repo.get_contents(path, ref=ref)
            return base64.b64decode(content.content).decode("utf-8")
        except GithubException as e:
            if e.status == 403 and attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def get_repo_structure(repo_full_name: str, ref: str = None) -> str:
    repo = _get_repo(repo_full_name)
    ref = ref or repo.default_branch
    logger.info(f"get_repo_structure: {repo_full_name}@{ref} (single tree API call)")
    try:
        tree = repo.get_git_tree(ref, recursive=True)
        lines = [item.path for item in tree.tree if item.type in ("blob", "tree")]
        logger.info(f"get_repo_structure: got {len(lines)} entries")
        return "\n".join(lines)
    except GithubException as e:
        logger.error(f"get_repo_structure failed: {e}")
        raise


async def _mcp_github_call(tool_name: str, arguments: dict) -> str:
    """Call a tool on the local GitHub MCP server via the MCP client protocol."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.github_mcp_server"],
        env={**os.environ, "PYTHONPATH": _PROJECT_DIR},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result.content[0].text if result.content else ""


def search_codebase(repo_full_name: str, query: str) -> list[str]:
    logger.info(f"search_codebase (via MCP): '{query}' in {repo_full_name}")
    try:
        raw = asyncio.run(_mcp_github_call(
            "search_codebase",
            {"repo_full_name": repo_full_name, "query": query},
        ))
        paths = json.loads(raw) if raw else []
        logger.info(f"search_codebase: {len(paths)} results")
        return paths
    except Exception as e:
        logger.warning(f"search_codebase MCP call failed ({e}) — returning empty list")
        return []


def create_pr(repo_full_name: str, title: str, body: str, head: str, base: str = None) -> str:
    logger.info(f"create_pr (via MCP): {repo_full_name} head={head}")
    try:
        url = asyncio.run(_mcp_github_call(
            "create_pr",
            {"repo_full_name": repo_full_name, "title": title, "body": body, "head": head, **({"base": base} if base else {})},
        ))
        logger.info(f"create_pr: {url}")
        return url
    except Exception as e:
        logger.warning(f"create_pr MCP call failed ({e}) — returning empty string")
        return ""
