import time
import base64
import logging
from github import Github, GithubException, BadCredentialsException
from src.config import GITHUB_TOKEN

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


def create_pr(repo_full_name: str, title: str, body: str, head: str, base: str = None) -> str:
    repo = _get_repo(repo_full_name)
    base = base or repo.default_branch
    logger.info(f"create_pr: {repo_full_name} head={head} base={base}")
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
