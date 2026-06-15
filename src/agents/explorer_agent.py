import json
import logging
import os
from datetime import datetime
from openai import OpenAI
from src.state import AgentState

logger = logging.getLogger(__name__)
from src.config import ACTIVE_MODEL, EXPLORER_MAX_FILES, EXPLORER_MAX_ITERATIONS
from src.tools.github_tools import read_file
from src.tools.shell_tools import get_imports

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"], timeout=60.0)


def _read_file_with_fallback(repo_full_name: str, path: str, repo_path: str) -> str:
    """Try local clone first, fall back to GitHub API."""
    local = os.path.join(repo_path, path)
    if os.path.isfile(local):
        with open(local, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return read_file(repo_full_name, path)


def explorer_agent(state: AgentState) -> AgentState:
    try:
        repo_full_name = _parse_repo(state["issue_url"])
        repo_path = _repo_path(state["issue_url"])
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
                # If iteration 1 read nothing, no point asking LLM — it has no context
                if not file_contents:
                    logger.warning("iteration 1 read 0 files — skipping further iterations")
                    break

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
                    logger.info(f"reading {path}")
                    content = _read_file_with_fallback(repo_full_name, path, repo_path)
                    file_contents[path] = content
                except Exception as e:
                    logger.warning(f"skipped {path}: {type(e).__name__}: {e}")
                    pass  # file not found in repo — skip silently

        # If no files were read, try a local-scan fallback before giving up
        if not file_contents:
            logger.warning("no files could be read from planner paths — trying local scan fallback")
            fallback_path = _pick_file_from_local_scan(repo_path, state, repo_full_name)
            if fallback_path:
                try:
                    content = _read_file_with_fallback(repo_full_name, fallback_path, repo_path)
                    file_contents[fallback_path] = content
                    logger.info(f"local scan fallback read: {fallback_path}")
                except Exception as e:
                    logger.warning(f"local scan fallback failed: {e}")

        if not file_contents:
            logger.warning("local scan fallback also found nothing — returning without broken_file")
            state["explorer_confidence"] = "low"
            state["trace"].append({
                "agent":         "explorer",
                "timestamp":     datetime.utcnow().isoformat(),
                "input_fields":  ["affected_files", "issue_body"],
                "output_fields": [],
                "llm_calls":     0,
                "tool_calls":    ["read_file"],
                "confidence":    "low",
                "files_read":    [],
                "iterations":    iterations,
            })
            return state

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
        f"Files identified by planner: {state['affected_files']}\n\n"
        f"Files read so far:\n" + ("\n".join(files_summary) if files_summary else "(none)") + "\n\n"
        f"Budget remaining: {budget_remaining} files\n\n"
        "Do you need to read more files to understand the bug?\n"
        "IMPORTANT: Only return file paths that exist in the planner's list above.\n"
        "Do NOT invent or guess file paths.\n"
        "If yes: {\"action\": \"read_more\", \"files\": [\"requests/utils.py\"]}\n"
        "If no:  {\"action\": \"ready\"}\n"
    )

    logger.info(f"_decide_next: calling OpenAI (files read so far: {len(file_contents)})")
    response = _client.chat.completions.create(
        model=ACTIVE_MODEL["model"],
        messages=[
            {"role": "system", "content": "You are an Explorer agent. Return only JSON."},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        timeout=30.0,
    )

    return json.loads(response.choices[0].message.content)


def _extract_findings(state: AgentState, file_contents: dict[str, str]) -> dict:
    files_read_so_far = "\n\n".join(
        f"### {path}\n{content[:3000]}" for path, content in file_contents.items()
    )
    budget_remaining = EXPLORER_MAX_FILES - len(file_contents)

    prompt_template = open("prompts/explorer.txt").read()
    prompt = prompt_template.format(
        issue_body=state["issue_body"],
        affected_files=state["affected_files"],
        files_read_so_far=files_read_so_far,
        budget_remaining=budget_remaining,
    )

    logger.info(f"_extract_findings: calling OpenAI ({len(file_contents)} files read)")
    response = _client.chat.completions.create(
        model=ACTIVE_MODEL["model"],
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        timeout=30.0,
    )

    result = json.loads(response.choices[0].message.content)
    _validate(result, ["broken_function", "broken_file", "current_behaviour",
                       "expected_behaviour", "confidence"])
    return result


def _pick_file_from_local_scan(repo_path: str, state: AgentState, repo_full_name: str) -> str:
    """Scan local repo for .py files and ask the LLM to pick the most relevant one."""
    py_files = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules",
                                                  "tests", "test", "docs", "build", "dist")]
        rel_root = os.path.relpath(root, repo_path).replace("\\", "/")
        for f in files:
            if f.endswith(".py"):
                path = f"{rel_root}/{f}" if rel_root != "." else f
                py_files.append(path)
        if len(py_files) >= 200:
            break

    if not py_files:
        return ""

    file_list = "\n".join(py_files[:200])
    prompt = (
        f"Issue: {state['issue_body'][:400]}\n\n"
        f"These .py files exist in the repo:\n{file_list}\n\n"
        "Which single file is most likely to contain the bug described in the issue?\n"
        "Return JSON: {\"broken_file\": \"path/to/file.py\"}"
    )

    logger.info("local scan fallback — calling LLM to pick file")
    try:
        response = _client.chat.completions.create(
            model=ACTIVE_MODEL["model"],
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=30.0,
        )
        result = json.loads(response.choices[0].message.content)
        return result.get("broken_file", "")
    except Exception as e:
        logger.warning(f"local scan fallback LLM call failed: {e}")
        return ""


def _parse_repo(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    return f"{parts[3]}/{parts[4]}"


def _repo_path(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    return os.path.join("repos", f"{parts[3]}__{parts[4]}")


def _validate(data: dict, required: list[str]) -> None:
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")
