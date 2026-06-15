import json
import os
from datetime import datetime
from openai import OpenAI
from src.state import AgentState
from src.config import ACTIVE_MODEL
from src.tools.patch_tools import apply_patch, validate_patch_syntax
from src.tools.shell_tools import run_shell

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"], timeout=60.0)
_MAX_SELF_CORRECTIONS = 3


def coder_agent(state: AgentState) -> AgentState:
    try:
        repo_path = _repo_path(state["issue_url"])
        relevant_code = _format_relevant_code(state["file_contents"])

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
                f"coder_agent failed: patch did not compile after "
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
        state["error"] = f"coder_agent failed: {str(e)}"

    return state


def _generate_and_verify(
    prompt: str, broken_file: str, repo_path: str
) -> tuple[dict | None, int, bool]:
    self_correction_attempts = 0
    compile_verified = False
    current_prompt = prompt

    for attempt in range(_MAX_SELF_CORRECTIONS):
        response = _client.chat.completions.create(
            model=ACTIVE_MODEL["model"],
            messages=[{"role": "user", "content": current_prompt}],
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        result = json.loads(raw)
        _validate(result, ["patch", "changed_files", "change_description"])

        patch = result["patch"]

        if not validate_patch_syntax(patch):
            self_correction_attempts += 1
            current_prompt = _correction_prompt(current_prompt, patch, "Patch syntax is invalid — missing ---, +++, or @@ headers.")
            continue

        apply_result = apply_patch(patch, cwd=repo_path)
        if not apply_result["success"]:
            self_correction_attempts += 1
            current_prompt = _correction_prompt(current_prompt, patch, f"apply_patch failed: {apply_result['error']}")
            continue

        compile_result = run_shell(
            f"python -m py_compile {broken_file}",
            cwd=repo_path,
        )
        if compile_result["returncode"] != 0:
            self_correction_attempts += 1
            current_prompt = _correction_prompt(current_prompt, patch, f"Compile failed: {compile_result['stderr']}")
            continue

        compile_verified = True
        return result, self_correction_attempts, compile_verified

    return None, self_correction_attempts, compile_verified


def _correction_prompt(original_prompt: str, failed_patch: str, error: str) -> str:
    return (
        f"{original_prompt}\n\n"
        f"--- PREVIOUS ATTEMPT FAILED ---\n"
        f"Patch attempted:\n{failed_patch}\n\n"
        f"Error: {error}\n\n"
        "Fix the patch and return a corrected JSON response. "
        "Do not repeat the same mistake."
    )


def _format_relevant_code(file_contents: dict[str, str]) -> str:
    return "\n\n".join(
        f"### {path}\n{content[:800]}" for path, content in file_contents.items()
    )


def _repo_path(issue_url: str) -> str:
    # repos are cloned to repos/owner__repo by the eval runner
    parts = issue_url.rstrip("/").split("/")
    owner, repo = parts[3], parts[4]
    return os.path.join("repos", f"{owner}__{repo}")


def _validate(data: dict, required: list[str]) -> None:
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")
