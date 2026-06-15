import difflib
import json
import logging
import os
from datetime import datetime
from openai import OpenAI
from src.state import AgentState

logger = logging.getLogger(__name__)
from src.config import ACTIVE_MODEL
from src.tools.shell_tools import run_shell

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"], timeout=60.0)
_MAX_SELF_CORRECTIONS = 3


def coder_agent(state: AgentState) -> AgentState:
    try:
        repo_path = _repo_path(state["issue_url"])
        _ensure_repo_cloned(repo_path, state["issue_url"])

        if not state.get("broken_file"):
            state["error"] = "coder_agent: broken_file is empty — no target to patch"
            logger.error(state["error"])
            return state

        relevant_code = _read_local_relevant_code(repo_path, state)

        prompt_template = open("prompts/coder.txt").read()
        prompt = prompt_template.format(
            issue_body=state["issue_body"],
            broken_function=state["broken_function"],
            broken_file=state["broken_file"],
            current_behaviour=state["current_behaviour"],
            expected_behaviour=state["expected_behaviour"],
            relevant_code=relevant_code,
            critic_feedback=state["critic_feedback"],
        )

        result, self_correction_attempts, compile_verified = _generate_and_verify(
            prompt, state["broken_file"], repo_path
        )

        if result is None:
            state["error"] = (
                f"coder_agent failed: patch did not apply after "
                f"{_MAX_SELF_CORRECTIONS} self-correction attempts"
            )
            return state

        state["patch"] = result["patch"]
        state["changed_files"] = result["changed_files"]
        state["change_description"] = result["change_description"]

        state["trace"].append({
            "agent":                  "coder",
            "timestamp":              datetime.utcnow().isoformat(),
            "input_fields":           ["issue_body", "broken_function", "broken_file",
                                       "current_behaviour", "expected_behaviour",
                                       "file_contents", "critic_feedback"],
            "output_fields":          ["patch", "changed_files", "change_description"],
            "llm_calls":              1 + self_correction_attempts,
            "tool_calls":             ["apply_patch", "run_shell"],
            "self_correction_attempts": self_correction_attempts,
            "compile_verified":       compile_verified,
        })

    except Exception as e:
        logger.error(f"coder_agent failed: {e}", exc_info=True)
        state["error"] = f"coder_agent failed: {str(e)}"

    return state


def _generate_and_verify(
    prompt: str, broken_file: str, repo_path: str
) -> tuple[dict | None, int, bool]:
    self_correction_attempts = 0
    compile_verified = False
    current_prompt = prompt
    local_file = os.path.join(repo_path, broken_file)

    for attempt in range(_MAX_SELF_CORRECTIONS):
        logger.info(f"attempt {attempt + 1}/{_MAX_SELF_CORRECTIONS} — calling OpenAI")
        response = _client.chat.completions.create(
            model=ACTIVE_MODEL["model"],
            messages=[{"role": "user", "content": current_prompt}],
            response_format={"type": "json_object"},
            timeout=60.0,
        )

        raw = response.choices[0].message.content
        result = json.loads(raw)
        _validate(result, ["old_code", "new_code", "changed_files", "change_description"])

        old_code = result["old_code"]
        new_code = result["new_code"]

        # Read current file content
        with open(local_file, "r", encoding="utf-8", errors="replace") as f:
            original = f.read()

        if old_code not in original:
            msg = (
                f"old_code not found in {broken_file}. "
                "Copy old_code VERBATIM from the file — every character must match exactly."
            )
            logger.warning(f"attempt {attempt + 1} failed: old_code not found in file")
            self_correction_attempts += 1
            current_prompt = _correction_prompt(current_prompt, old_code, new_code, msg)
            continue

        # Apply string replacement
        modified = original.replace(old_code, new_code, 1)
        with open(local_file, "w", encoding="utf-8") as f:
            f.write(modified)
        logger.info(f"applied replacement to {broken_file}")

        # Syntax check
        compile_result = run_shell(f"python -m py_compile {broken_file}", cwd=repo_path)
        if compile_result["returncode"] != 0:
            msg = f"Compile failed: {compile_result['stderr']}"
            logger.warning(f"attempt {attempt + 1} failed: {msg}")
            # Revert
            with open(local_file, "w", encoding="utf-8") as f:
                f.write(original)
            self_correction_attempts += 1
            current_prompt = _correction_prompt(current_prompt, old_code, new_code, msg)
            continue

        # Generate unified diff for the patch field (for PR and eval output)
        patch = _make_unified_diff(original, modified, broken_file)
        compile_verified = True
        return {
            "patch": patch,
            "changed_files": result["changed_files"],
            "change_description": result["change_description"],
        }, self_correction_attempts, compile_verified

    return None, self_correction_attempts, compile_verified


def _make_unified_diff(original: str, modified: str, file_path: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )
    return "".join(diff)


def _correction_prompt(original_prompt: str, old_code: str, new_code: str, error: str) -> str:
    return (
        f"{original_prompt}\n\n"
        f"--- PREVIOUS ATTEMPT FAILED ---\n"
        f"old_code attempted:\n{old_code}\n\n"
        f"new_code attempted:\n{new_code}\n\n"
        f"Error: {error}\n\n"
        "Fix old_code so it is an exact verbatim substring of the file shown above. "
        "Copy it character-for-character. Do not paraphrase."
    )


def _read_local_relevant_code(repo_path: str, state: AgentState) -> str:
    parts = []
    broken_file = state.get("broken_file", "")

    if broken_file:
        local_path = os.path.join(repo_path, broken_file)
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            logger.info(f"read {len(content)} chars from local {broken_file}")
            parts.append(
                f"### {broken_file} (EXACT LOCAL CONTENT — copy old_code verbatim from here)\n{content}"
            )
        else:
            logger.warning(f"local file not found: {local_path}")

    for path, content in state.get("file_contents", {}).items():
        if path != broken_file:
            parts.append(f"### {path}\n{content[:3000]}")

    return "\n\n".join(parts)


def _repo_path(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    owner, repo = parts[3], parts[4]
    return os.path.join("repos", f"{owner}__{repo}")


def _ensure_repo_cloned(repo_path: str, issue_url: str) -> None:
    if os.path.isdir(repo_path):
        logger.debug(f"repo already cloned at {repo_path}")
        return
    parts = issue_url.rstrip("/").split("/")
    owner, repo = parts[3], parts[4]
    clone_url = f"https://github.com/{owner}/{repo}.git"
    os.makedirs("repos", exist_ok=True)
    logger.info(f"cloning {clone_url} -> {repo_path}")
    result = run_shell(f"git clone {clone_url} {repo_path}", timeout=300)
    if result["returncode"] != 0:
        raise RuntimeError(f"git clone failed: {result['stderr'].strip()}")


def _validate(data: dict, required: list[str]) -> None:
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")
