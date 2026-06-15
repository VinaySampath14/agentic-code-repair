import json
from datetime import datetime
from openai import OpenAI
from src.state import AgentState
from src.config import ACTIVE_MODEL, EXPLORER_MAX_FILES, EXPLORER_MAX_ITERATIONS
from src.tools.github_tools import read_file
from src.tools.shell_tools import get_imports

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"])


def explorer_agent(state: AgentState) -> AgentState:
    try:
        repo_full_name = _parse_repo(state["issue_url"])
        file_contents: dict[str, str] = {}
        llm_calls = 0
        iterations = 0

        for iteration in range(1, EXPLORER_MAX_ITERATIONS + 1):
            iterations = iteration

            if len(file_contents) >= EXPLORER_MAX_FILES:
                break

            if iteration == 1:
                # Read all planner-identified files directly
                batch = list(state["affected_files"])
            else:
                # LLM decides what to read next
                decision = _decide_next(state, file_contents)
                llm_calls += 1

                if decision["action"] == "ready":
                    break

                batch = [
                    f for f in decision.get("files", [])
                    if f not in file_contents
                ]

            budget_remaining = EXPLORER_MAX_FILES - len(file_contents)
            for path in batch[:budget_remaining]:
                try:
                    content = read_file(repo_full_name, path)
                    file_contents[path] = content
                except Exception:
                    pass  # file not found in repo — skip silently

        # Final LLM call: extract structured findings from everything read
        result = _extract_findings(state, file_contents)
        llm_calls += 1

        state["file_contents"] = file_contents
        state["broken_function"] = result["broken_function"]
        state["broken_file"] = result["broken_file"]
        state["current_behaviour"] = result["current_behaviour"]
        state["expected_behaviour"] = result["expected_behaviour"]
        state["explorer_confidence"] = result["confidence"]

        # Budget hit without high confidence → force low
        if len(file_contents) >= EXPLORER_MAX_FILES and result["confidence"] != "high":
            state["explorer_confidence"] = "low"

        state["trace"].append({
            "agent":         "explorer",
            "timestamp":     datetime.utcnow().isoformat(),
            "input_fields":  ["affected_files", "issue_body"],
            "output_fields": ["file_contents", "broken_function", "broken_file",
                              "current_behaviour", "expected_behaviour", "explorer_confidence"],
            "llm_calls":     llm_calls,
            "tool_calls":    ["read_file", "get_imports"],
            "confidence":    state["explorer_confidence"],
            "files_read":    list(file_contents.keys()),
            "iterations":    iterations,
        })

    except Exception as e:
        state["error"] = f"explorer_agent failed: {str(e)}"

    return state


def _decide_next(state: AgentState, file_contents: dict[str, str]) -> dict:
    files_summary = []
    for path, content in file_contents.items():
        imports = get_imports(content)
        files_summary.append(f"{path}:\n  imports: {imports}")

    budget_remaining = EXPLORER_MAX_FILES - len(file_contents)

    user = (
        f"Issue: {state['issue_body'][:300]}\n\n"
        f"Files read so far:\n" + "\n".join(files_summary) + "\n\n"
        f"Budget remaining: {budget_remaining} files\n\n"
        "Do you need to read more files to understand the bug?\n"
        "If yes: {\"action\": \"read_more\", \"files\": [\"path/to/file.py\"]}\n"
        "If no:  {\"action\": \"ready\"}\n"
        "Only list files directly relevant to the bug."
    )

    response = _client.chat.completions.create(
        model=ACTIVE_MODEL["model"],
        messages=[
            {"role": "system", "content": "You are an Explorer agent. Return only JSON."},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)


def _extract_findings(state: AgentState, file_contents: dict[str, str]) -> dict:
    files_read_so_far = "\n\n".join(
        f"### {path}\n{content[:600]}" for path, content in file_contents.items()
    )
    budget_remaining = EXPLORER_MAX_FILES - len(file_contents)

    prompt_template = open("prompts/explorer.txt").read()
    prompt = prompt_template.format(
        issue_body=state["issue_body"],
        affected_files=state["affected_files"],
        files_read_so_far=files_read_so_far,
        budget_remaining=budget_remaining,
    )

    response = _client.chat.completions.create(
        model=ACTIVE_MODEL["model"],
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    _validate(result, ["broken_function", "broken_file", "current_behaviour",
                       "expected_behaviour", "confidence"])
    return result


def _parse_repo(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    return f"{parts[3]}/{parts[4]}"


def _validate(data: dict, required: list[str]) -> None:
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")
