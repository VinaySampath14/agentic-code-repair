import json
import logging
import os
from datetime import datetime
from src.state import AgentState

logger = logging.getLogger(__name__)
from src.config import ACTIVE_MODEL, FIX_SCORE_THRESHOLD, CODER_MAX_RETRIES
from src.tracing import OpenAI, observe, langfuse_context
from src.tools.test_tools import run_pytest, run_linter
from src.tools.shell_tools import run_shell

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"], timeout=60.0)


@observe(name="critic-agent")
def critic_agent(state: AgentState) -> AgentState:
    if langfuse_context is not None:
        langfuse_context.update_current_trace(session_id=state.get("instance_id", ""))
    try:
        repo_path = _repo_path(state["issue_url"])

        if not os.path.isdir(repo_path):
            state["error"] = f"critic_agent: repo not cloned at {repo_path}"
            state["test_results"] = {"decision": "fail"}
            state["fix_score"] = 0.0
            state["critic_feedback"] = "Repo not available locally — cannot run tests."
            logger.error(state["error"])
            return state

        if not state.get("patch", "").strip():
            state["test_results"] = {"decision": "fail"}
            state["fix_score"] = 0.0
            state["critic_feedback"] = "No patch was produced — coder did not generate a change."
            logger.warning("critic_agent: empty patch — scoring 0.0 without running tests")
            return state

        # Linter always runs (fast, no subprocess overhead)
        linter_result = run_linter(repo_path, state["broken_file"])
        linter_errors = linter_result.get("issue_count", 0)
        code_quality = 1.0 if linter_errors == 0 else 0.5

        tests_passed = 0
        tests_failed = 0
        tests_before = 0
        post = {}
        test_pass_rate = 0.0
        no_regression  = 1.0

        if state.get("quick_mode"):
            # Skip pytest — use LLM semantic scoring directly (for MCP/demo use)
            logger.info("quick_mode: skipping test runner, using LLM semantic scoring")
            tests_ran = False
        else:
            # Determine test path — prefer SWE-bench FAIL_TO_PASS test IDs
            fail_to_pass = state.get("fail_to_pass", [])
            test_path = _build_test_path(repo_path, fail_to_pass)
            logger.info(f"test_path: {test_path!r} (fail_to_pass={len(fail_to_pass)} tests)")

            # Baseline: stash patch → run tests → restore patch
            logger.info("running baseline tests (git stash)")
            run_shell("git stash", cwd=repo_path)
            baseline = run_pytest(repo_path, test_path=test_path)
            tests_before = baseline.get("passed", 0)
            logger.info(f"baseline: {tests_before} passing")
            run_shell("git stash pop", cwd=repo_path)
            logger.info("running post-patch tests")

            post = run_pytest(repo_path, test_path=test_path)
            tests_passed = post.get("passed", 0)
            tests_failed = post.get("failed", 0)
            tests_ran = (tests_passed + tests_failed) > 0

        if tests_ran:
            # Test-based scoring
            test_pass_rate = tests_passed / (tests_passed + tests_failed)
            no_regression  = (tests_passed / tests_before) if tests_before > 0 else 1.0
            fix_score = round(
                (0.5 * test_pass_rate) + (0.3 * no_regression) + (0.2 * code_quality),
                3,
            )
            logger.info(f"test-based score: pass_rate={test_pass_rate:.2f} no_reg={no_regression:.2f} quality={code_quality}")
        else:
            # Tests couldn't run (old base_commit env incompatibility) — use LLM semantic score
            logger.info("0 tests collected — falling back to LLM semantic scoring")
            semantic_score = _llm_score_patch(state)
            fix_score = round((0.8 * semantic_score) + (0.2 * code_quality), 3)
            logger.info(f"semantic score: {semantic_score:.2f} → fix_score={fix_score}")

        # Decision — retry_count exhaustion takes priority
        if state["retry_count"] >= CODER_MAX_RETRIES:
            decision = "fail"
        elif fix_score >= FIX_SCORE_THRESHOLD:
            decision = "approve"
        else:
            decision = "retry"

        # Semantic check — only when tests pass, before we approve
        semantic_result = {}
        llm_calls = 0
        critic_feedback = ""
        if decision == "approve":
            semantic_result = _semantic_check(state)
            llm_calls = 1
            if not semantic_result.get("addresses_root_cause", True):
                reason = semantic_result.get("reason", "patch does not address root cause")
                logger.warning(f"semantic check failed: {reason}")
                decision = "retry" if state["retry_count"] < CODER_MAX_RETRIES else "fail"
                critic_feedback = f"Semantic check: {reason}"

        # Actionable feedback only when Coder needs to retry
        if decision in ("retry", "fail") and not critic_feedback:
            critic_feedback = _generate_feedback(state, post, fix_score, decision, repo_path)
            llm_calls += 1

        # Reset working tree so coder always starts from a clean state on retry
        if decision in ("retry", "fail"):
            run_shell("git checkout -- .", cwd=repo_path)
            logger.info("reset working tree to clean state")

        state["test_results"] = {
            "decision":      decision,
            "tests_passed":  tests_passed,
            "tests_failed":  tests_failed,
            "tests_before":  tests_before,
            "test_pass_rate": round(test_pass_rate, 3),
            "no_regression": round(no_regression, 3),
            "code_quality":  code_quality,
            "linter_errors": linter_errors,
        }
        state["fix_score"] = fix_score
        state["critic_feedback"] = critic_feedback
        logger.info(f"fix_score={fix_score} decision={decision}")

        state["trace"].append({
            "agent":              "critic",
            "timestamp":          datetime.utcnow().isoformat(),
            "input_fields":       ["patch", "changed_files", "broken_file"],
            "output_fields":      ["test_results", "fix_score", "critic_feedback"],
            "llm_calls":          llm_calls,
            "tool_calls":         ["run_pytest", "run_linter", "run_shell"],
            "tests_passed":       tests_passed,
            "tests_failed":       tests_failed,
            "tests_before":       tests_before,
            "fix_score":          fix_score,
            "decision":           decision,
            "semantic_check":     semantic_result,
        })

    except Exception as e:
        logger.error(f"critic_agent failed: {e}", exc_info=True)
        state["error"] = f"critic_agent failed: {str(e)}"

    return state


def _semantic_check(state: AgentState) -> dict:
    prompt_template = open("prompts/critic_semantic.txt").read()
    prompt = prompt_template.format(
        issue_body=state["issue_body"],
        patch=state["patch"],
        changed_files=state["changed_files"],
    )

    logger.info("semantic check — calling OpenAI")
    response = _client.chat.completions.create(
        model=ACTIVE_MODEL["model"],
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=200,
        timeout=30.0,
    )

    try:
        return json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, KeyError):
        return {"addresses_root_cause": True, "reason": "parse error — defaulting to approve"}


def _generate_feedback(
    state: AgentState,
    post_results: dict,
    fix_score: float,
    decision: str,
    repo_path: str,
) -> str:
    prompt_template = open("prompts/critic.txt").read()
    prompt = prompt_template.format(
        patch=state["patch"],
        changed_files=state["changed_files"],
        test_dir=repo_path,
        retry_count=state["retry_count"] + 1,
    )

    prompt += (
        f"\n\nActual results:\n"
        f"  tests_passed : {post_results.get('passed', 0)}\n"
        f"  tests_failed : {post_results.get('failed', 0)}\n"
        f"  fix_score    : {fix_score}\n"
        f"  decision     : {decision}\n"
        f"\nRaw pytest output:\n{post_results.get('raw', '(no raw output)')}\n\n"
        "Write exactly one sentence of actionable feedback for the Coder. "
        "Name the specific test that failed. Name the specific error or assertion. "
        "Do not write a generic message. The Coder reads this on its next attempt."
    )

    logger.info("generating feedback — calling OpenAI")
    response = _client.chat.completions.create(
        model=ACTIVE_MODEL["model"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
        timeout=30.0,
    )

    return response.choices[0].message.content.strip()


def _llm_score_patch(state: AgentState) -> float:
    """Ask the LLM to score the patch 0.0–1.0 when tests can't run."""
    prompt = (
        f"You are a senior code reviewer. Score this patch from 0.0 to 1.0.\n\n"
        f"Issue:\n{state['issue_body'][:600]}\n\n"
        f"Patch:\n{state.get('patch', '')[:2000]}\n\n"
        f"Score criteria:\n"
        f"  1.0 = patch clearly fixes the root cause described in the issue\n"
        f"  0.7 = patch addresses the issue but may have edge cases\n"
        f"  0.4 = patch is related but unlikely to fully fix the issue\n"
        f"  0.0 = patch is wrong or unrelated\n\n"
        f"Return JSON: {{\"score\": 0.0, \"reason\": \"one sentence\"}}"
    )
    try:
        response = _client.chat.completions.create(
            model=ACTIVE_MODEL["model"],
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=100,
            timeout=30.0,
        )
        result = json.loads(response.choices[0].message.content)
        score = float(result.get("score", 0.5))
        logger.info(f"LLM patch score: {score} — {result.get('reason', '')}")
        return max(0.0, min(1.0, score))
    except Exception as e:
        logger.warning(f"LLM scoring failed: {e} — defaulting to 0.5")
        return 0.5


def _build_test_path(repo_path: str, fail_to_pass: list[str]) -> str:
    """Convert SWE-bench FAIL_TO_PASS test IDs into a pytest-compatible path string."""
    if not fail_to_pass:
        return ""
    # SWE-bench IDs look like "tests/test_foo.py::TestClass::test_method"
    # Deduplicate at the file level and keep full node IDs for precision
    seen_files: set[str] = set()
    node_ids: list[str] = []
    for test_id in fail_to_pass:
        file_part = test_id.split("::")[0]
        full_path = os.path.join(repo_path, file_part)
        if os.path.exists(full_path):
            node_ids.append(test_id)
            seen_files.add(file_part)
        else:
            # File not found at this commit — fall back to file name only
            if file_part not in seen_files and os.path.exists(full_path):
                seen_files.add(file_part)
    if node_ids:
        return " ".join(node_ids)
    # If no test files exist locally, return empty (caller falls back to default)
    return ""


def _repo_path(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    owner, repo = parts[3], parts[4]
    return os.path.join("repos", f"{owner}__{repo}")
