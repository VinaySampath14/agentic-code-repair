import time
import base64
import logging
from github import Github, GithubException
from src.config import GITHUB_TOKEN

logger = logging.getLogger(__name__)
_client = Github(GITHUB_TOKEN)


def _get_repo(repo_full_name: str):
    for attempt in range(3):
        try:
            return _client.get_repo(repo_full_name)
        except GithubException as e:
            if e.status == 403 and attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def read_file(repo_full_name: str, path: str, ref: str = "main") -> str:
    logger.debug(f"read_file: {repo_full_name}/{path}@{ref}")
    repo = _get_repo(repo_full_name)
    for attempt in range(3):
        try:
            content = repo.get_contents(path, ref=ref)
            return base64.b64decode(content.content).decode("utf-8")
        except GithubException as e:
            if e.status == 403 and attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def get_repo_structure(repo_full_name: str, ref: str = "main") -> str:
    """Single GitHub API call using the Git tree endpoint — no recursive traversal."""
    logger.info(f"get_repo_structure: {repo_full_name}@{ref} (single tree API call)")
    repo = _get_repo(repo_full_name)
    try:
        tree = repo.get_git_tree(ref, recursive=True)
        lines = [item.path for item in tree.tree if item.type in ("blob", "tree")]
        logger.info(f"get_repo_structure: got {len(lines)} entries")
        return "\n".join(lines)
    except GithubException as e:
        logger.error(f"get_repo_structure failed: {e}")
        raise


def search_codebase(repo_full_name: str, query: str) -> list[str]:
    logger.info(f"search_codebase: '{query}' in {repo_full_name}")
    for attempt in range(3):
        try:
            results = _client.search_code(f"{query} repo:{repo_full_name}")
            paths = [item.path for item in results]
            logger.info(f"search_codebase: {len(paths)} results")
            return paths
        except GithubException as e:
            if e.status == 403 and attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def create_pr(repo_full_name: str, title: str, body: str, head: str, base: str = "main") -> str:
    logger.info(f"create_pr: {repo_full_name} head={head}")
    repo = _get_repo(repo_full_name)
    for attempt in range(3):
        try:
            pr = repo.create_pull(title=title, body=body, head=head, base=base, draft=True)
            logger.info(f"create_pr: {pr.html_url}")
            return pr.html_url
        except GithubException as e:
            if e.status == 403 and attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise
