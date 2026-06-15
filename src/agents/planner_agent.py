import json
from datetime import datetime
from openai import OpenAI
from src.state import AgentState
from src.config import ACTIVE_MODEL
from src.tools.github_tools import get_repo_structure, search_codebase

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"], timeout=60.0)


def planner_agent(state: AgentState) -> AgentState:
    try:
        repo_full_name = _parse_repo(state["issue_url"])
        repo_structure = get_repo_structure(repo_full_name)

        search_results = search_codebase(
            repo_full_name,
            state["issue_body"][:200]
        )

        prompt_template = open("prompts/planner.txt").read()
        prompt = prompt_template.format(
            issue_url=state["issue_url"],
            issue_body=state["issue_body"],
            repo_structure=repo_structure,
            search_results=search_results,
        )

        response = _client.chat.completions.create(
            model=ACTIVE_MODEL["model"],
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        result = json.loads(raw)

        _validate(result, ["core_problem", "affected_files", "complexity", "confidence"])

        state["core_problem"] = result["core_problem"]
        state["affected_files"] = result["affected_files"]
        state["complexity"] = result["complexity"]
        state["planner_confidence"] = result["confidence"]

        state["trace"].append({
            "agent":         "planner",
            "timestamp":     datetime.utcnow().isoformat(),
            "input_fields":  ["issue_body", "issue_url"],
            "output_fields": ["affected_files", "core_problem", "complexity", "planner_confidence"],
            "llm_calls":     1,
            "tool_calls":    ["get_repo_structure", "search_codebase"],
            "confidence":    state["planner_confidence"],
        })

    except Exception as e:
        state["error"] = f"planner_agent failed: {str(e)}"

    return state


def _parse_repo(issue_url: str) -> str:
    # https://github.com/owner/repo/issues/123 → owner/repo
    parts = issue_url.rstrip("/").split("/")
    return f"{parts[3]}/{parts[4]}"


def _validate(data: dict, required: list[str]) -> None:
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")
