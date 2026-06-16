import difflib
import json
import logging
import os
from datetime import datetime
from src.state import AgentState

logger = logging.getLogger(__name__)
from src.config import ACTIVE_MODEL
from src.tracing import OpenAI, observe, langfuse_context
from src.tools.shell_tools import run_shell

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"], timeout=60.0)
_MAX_SELF_CORRECTIONS = 3


@observe(name="coder-agent")
def coder_agent(state: AgentState) -> AgentState:
    if langfuse_context is not None:
        langfuse_context.update_current_trace(session_id=state.get("instance_id", ""))
    try:
        repo_path = _repo_path(state["issue_url"])
        _ensure_repo_cloned(repo_path, state["issue_url"])

        broken_file = state.get("broken_file", "").strip()
        if not broken_file or broken_file.lower() in ("n/a", "none", "unknown"):
            state["error"] = f"coder_agent: broken_file is '{broken_file}' — Explorer could not identify the file to patch"
            logger.error(state["error"])
            state["fix_score"] = 0.0
            state["fix_score"] = 0.0
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
    local_file = _resolve_local_path(repo_path, broken_file)

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
            logger.warning(
                f"attempt {attempt + 1} failed: old_code not found in file\n"
                f"  old_code attempted ({len(old_code)} chars): {repr(old_code[:200])}"
            )
            self_correction_attempts += 1
            current_prompt = _correction_prompt(current_prompt, old_code, new_code, msg, original)
            continue

        # Apply string replacement
        modified = original.replace(old_code, new_code, 1)
        with open(local_file, "w", encoding="utf-8") as f:
            f.write(modified)
        logger.info(f"applied replacement to {broken_file}")

        # Syntax check — use path relative to repo_path so cwd works correctly
        rel_for_compile = os.path.relpath(local_file, repo_path)
        compile_result = run_shell(f"python -m py_compile {rel_for_compile}", cwd=repo_path)
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


def _correction_prompt(original_prompt: str, old_code: str, new_code: str, error: str, file_content: str = "") -> str:
    nearest = _find_nearest_block(old_code, file_content) if file_content else ""
    hint = (
        f"\nNearest matching block found in the file (copy THIS exactly):\n"
        f"```\n{nearest}\n```\n"
        if nearest else ""
    )
    return (
        f"{original_prompt}\n\n"
        f"--- PREVIOUS ATTEMPT FAILED ---\n"
        f"old_code attempted:\n{old_code}\n\n"
        f"new_code attempted:\n{new_code}\n\n"
        f"Error: {error}\n"
        f"{hint}\n"
        "Fix old_code so it is an exact verbatim substring of the file shown above. "
        "Copy it character-for-character including all whitespace and indentation. Do not paraphrase."
    )


def _find_nearest_block(old_code: str, file_content: str) -> str:
    """Find the closest matching block in file_content to old_code using line-level similarity."""
    old_lines = old_code.splitlines()
    file_lines = file_content.splitlines()
    n = len(old_lines)
    if n == 0 or len(file_lines) < n:
        return ""

    best_ratio = 0.0
    best_start = 0
    for i in range(len(file_lines) - n + 1):
        block = file_lines[i : i + n]
        ratio = difflib.SequenceMatcher(None, old_lines, block).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i

    if best_ratio < 0.4:
        return ""

    return "\n".join(file_lines[best_start : best_start + n])


_MAX_FILE_LINES = 500
_PATH_STRIP_PREFIXES = ("src/", "lib/", "source/")


def _resolve_local_path(repo_path: str, broken_file: str) -> str:
    """Return the on-disk path for broken_file, trying prefix strips then basename search."""
    candidate = os.path.join(repo_path, broken_file)
    if os.path.exists(candidate):
        return candidate
    # Try stripping common directory prefixes (src/, lib/, source/)
    for prefix in _PATH_STRIP_PREFIXES:
        if broken_file.startswith(prefix):
            stripped = broken_file[len(prefix):]
            alt = os.path.join(repo_path, stripped)
            if os.path.exists(alt):
                logger.info(f"path fallback: {broken_file} -> {stripped}")
                return alt
    # Try basename search — handles renamed files (e.g. _ridge.py -> ridge.py)
    basename = os.path.basename(broken_file)
    dirname  = os.path.dirname(broken_file)
    for root, _dirs, files in os.walk(repo_path):
        for fname in files:
            if fname == basename or fname == basename.lstrip("_"):
                found = os.path.join(root, fname)
                rel = os.path.relpath(found, repo_path).replace("\\", "/")
                # Must be in roughly the same directory
                if os.path.dirname(rel) == dirname or os.path.dirname(rel).endswith(os.path.basename(dirname)):
                    logger.info(f"basename fallback: {broken_file} -> {rel}")
                    return found
    return candidate  # return original so FileNotFoundError is raised with correct path


def _read_local_relevant_code(repo_path: str, state: AgentState) -> str:
    parts = []
    broken_file = state.get("broken_file", "")

    if broken_file:
        local_path = _resolve_local_path(repo_path, broken_file)
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                raw_lines = f.readlines()
            logger.info(f"read {len(raw_lines)} lines from local {broken_file}")

            # Focus on broken_function if file is large
            focused = _focus_on_function(raw_lines, state.get("broken_function", ""))
            raw_content = "".join(focused["lines"])

            note = ""
            if focused["truncated"]:
                note = (
                    f"(showing lines {focused['start']}-{focused['end']} of "
                    f"{len(raw_lines)} total)\n"
                )

            parts.append(
                f"### {broken_file} (EXACT LOCAL CONTENT — copy old_code verbatim from here)\n"
                f"{note}\n"
                f"{raw_content}"
            )
        else:
            logger.warning(f"local file not found: {local_path}")

    for path, content in state.get("file_contents", {}).items():
        if path != broken_file:
            parts.append(f"### {path}\n{content[:3000]}")

    return "\n\n".join(parts)


def _focus_on_function(lines: list[str], broken_function: str) -> dict:
    """Return a window of lines centred on broken_function, or the first MAX lines."""
    total = len(lines)
    if broken_function and total > _MAX_FILE_LINES:
        for i, line in enumerate(lines):
            if broken_function in line:
                start = max(0, i - 20)
                end   = min(total, i + _MAX_FILE_LINES - 20)
                return {"lines": lines[start:end], "start": start + 1,
                        "end": end, "truncated": True}
    # No function hint or file is small — return up to MAX lines
    truncated = total > _MAX_FILE_LINES
    end = min(total, _MAX_FILE_LINES)
    return {"lines": lines[:end], "start": 1, "end": end, "truncated": truncated}


def _number_lines(lines: list[str], start: int = 1) -> str:
    return "".join(f"{start + i:>5}: {line}" for i, line in enumerate(lines))


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
