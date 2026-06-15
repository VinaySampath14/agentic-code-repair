from typing import TypedDict


class AgentState(TypedDict):
    issue_url: str
    issue_body: str
    affected_files: list[str]
    file_contents: dict[str, str]
    patch: str
    test_results: dict
    fix_score: float
    pr_url: str
    trace: list[dict]
    retry_count: int
    error: str | None
