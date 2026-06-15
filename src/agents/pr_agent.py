import json
import logging
import os
from datetime import datetime
from github import Github, GithubException
from openai import OpenAI
from src.state import AgentState

logger = logging.getLogger(__name__)
from src.config import ACTIVE_MODEL, GITHUB_TOKEN
from src.tools.github_tools import create_pr

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"], timeout=60.0)
_gh = Github(GITHUB_TOKEN)


def pr_agent(state: AgentState) -> AgentState:
    try:
        content = _generate_pr_content(state)
        pr_title = content["pr_title"]
        pr_body  = content["pr_body"]
        branch   = f"agent-fix/{state['instance_id']}"

        if state["eval_mode"]:
            eval_file = _write_eval_prediction(state)
            pr_url = f"eval:{state['instance_id']}"

            state["pr_url"] = pr_url
            state["trace"].append({
                "agent":         "pr_agent",
                "timestamp":     datetime.utcnow().isoformat(),
                "input_fields":  ["patch", "instance_id", "fix_score", "test_results"],
                "output_fields": ["pr_url"],
                "llm_calls":     1,
                "tool_calls":    [],
                "mode":          "eval",
                "pr_url":        pr_url,
                "eval_file":     eval_file,
            })

        else:
            repo_full_name = _parse_repo(state["issue_url"])
            pr_url = create_pr(
                repo_full_name=repo_full_name,
                title=pr_title,
                body=pr_body,
                head=branch,
                base="main",
            )
            _add_label(pr_url, "agent-generated")

            state["pr_url"] = pr_url
            state["trace"].append({
                "agent":         "pr_agent",
                "timestamp":     datetime.utcnow().isoformat(),
                "input_fields":  ["patch", "instance_id", "fix_score", "test_results"],
                "output_fields": ["pr_url"],
                "llm_calls":     1,
                "tool_calls":    ["create_pr", "add_label"],
                "mode":          "live",
                "pr_url":        pr_url,
            })

    except Exception as e:
        logger.error(f"pr_agent failed: {e}", exc_info=True)
        state["error"] = f"pr_agent failed: {str(e)}"

    return state


def _generate_pr_content(state: AgentState) -> dict:
    prompt_template = open("prompts/pr_agent.txt").read()
    prompt = prompt_template.format(
        issue_body=state["issue_body"],
        change_description=state["change_description"],
        patch=state["patch"],
        test_results=json.dumps(state["test_results"], indent=2),
        fix_score=state["fix_score"],
        instance_id=state["instance_id"],
    )

    logger.info("calling OpenAI for PR content")
    response = _client.chat.completions.create(
        model=ACTIVE_MODEL["model"],
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        timeout=30.0,
    )

    result = json.loads(response.choices[0].message.content)
    _validate(result, ["pr_title", "pr_body"])

    # Enforce title constraints
    if not result["pr_title"].startswith("fix: "):
        result["pr_title"] = "fix: " + result["pr_title"].removeprefix("fix: ")
    if len(result["pr_title"]) > 72:
        result["pr_title"] = result["pr_title"][:72]

    return result


def _write_eval_prediction(state: AgentState) -> str:
    predictions_dir = os.path.join("evals", "predictions")
    os.makedirs(predictions_dir, exist_ok=True)
    eval_file = os.path.join(predictions_dir, f"{state['instance_id']}.diff")
    with open(eval_file, "w") as f:
        f.write(state["patch"])
    return eval_file


def _add_label(pr_url: str, label: str) -> None:
    try:
        parts = pr_url.rstrip("/").split("/")
        repo_full_name = f"{parts[3]}/{parts[4]}"
        pr_number = int(parts[6])
        repo = _gh.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)
        pr.add_to_labels(label)
    except GithubException:
        pass  # label may not exist — non-fatal


def _parse_repo(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    return f"{parts[3]}/{parts[4]}"


def _validate(data: dict, required: list[str]) -> None:
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")
