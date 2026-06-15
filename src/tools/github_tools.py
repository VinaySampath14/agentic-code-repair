import time
import base64
from github import Github, GithubException
from src.config import GITHUB_TOKEN

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


def get_repo_structure(repo_full_name: str, ref: str = "main", max_depth: int = 3) -> str:
    repo = _get_repo(repo_full_name)
    lines = []

    def _walk(path: str, depth: int):
        if depth > max_depth:
            return
        for attempt in range(3):
            try:
                contents = repo.get_contents(path, ref=ref)
                break
            except GithubException as e:
                if e.status == 403 and attempt < 2:
                    time.sleep(2 ** attempt)
                else:
                    return
        for item in contents:
            lines.append("  " * depth + item.path)
            if item.type == "dir":
                _walk(item.path, depth + 1)

    _walk("", 0)
    return "\n".join(lines)


def search_codebase(repo_full_name: str, query: str) -> list[str]:
    for attempt in range(3):
        try:
            results = _client.search_code(f"{query} repo:{repo_full_name}")
            return [item.path for item in results]
        except GithubException as e:
            if e.status == 403 and attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise


def create_pr(repo_full_name: str, title: str, body: str, head: str, base: str = "main") -> str:
    repo = _get_repo(repo_full_name)
    for attempt in range(3):
        try:
            pr = repo.create_pull(title=title, body=body, head=head, base=base, draft=True)
            return pr.html_url
        except GithubException as e:
            if e.status == 403 and attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise
