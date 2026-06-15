import json
import logging
import os
from datetime import datetime
from openai import OpenAI
from src.state import AgentState

logger = logging.getLogger(__name__)
from src.config import ACTIVE_MODEL, FIX_SCORE_THRESHOLD, CODER_MAX_RETRIES
from src.tools.test_tools import run_pytest, run_linter
from src.tools.shell_tools import run_shell

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"], timeout=60.0)


def critic_agent(state: AgentState) -> AgentState:
    try:
        repo_path = _repo_path(state["issue_url"])

        if not os.path.isdir(repo_path):
            state["error"] = f"critic_agent: repo not cloned at {repo_path}"
            state["test_results"] = {"decision": "fail"}
            state["fix_score"] = 0.0
            state["critic_feedback"] = "Repo not available locally — cannot run tests."
            logger.error(state["error"])
            return state

        # Baseline: stash patch → run tests → restore patch
        logger.info("running baseline tests (git stash)")
        run_shell("git stash", cwd=repo_path)
        baseline = run_pytest(repo_path)
        tests_before = baseline.get("passed", 0)
        logger.info(f"baseline: {tests_before} passing")
        run_shell("git stash pop", cwd=repo_path)
        logger.info("running post-patch tests")

        # Post-patch results
        post = run_pytest(repo_path)
        tests_passed = post.get("passed", 0)
        tests_failed = post.get("failed", 0)

        # Linter
        linter_result = run_linter(repo_path, state["broken_file"])
        linter_errors = linter_result.get("issue_count", 0)

        # fix_score — exact formula, explicit edge cases
        if tests_passed + tests_failed == 0:
            test_pass_rate = 0.0
        else:
            test_pass_rate = tests_passed / (tests_passed + tests_failed)

        if tests_before == 0:
            no_regression = 1.0
        else:
            no_regression = tests_passed / tests_before

        code_quality = 1.0 if linter_errors == 0 else 0.5

        fix_score = round(
            (0.5 * test_pass_rate) + (0.3 * no_regression) + (0.2 * code_quality),
            3,
        )

        # Decision — retry_count exhaustion takes priority
        if state["retry_count"] >= CODER_MAX_RETRIES:
            decision = "fail"
        elif fix_score >= FIX_SCORE_THRESHOLD:
            decision = "approve"
        else:
            decision = "retry"

        # Actionable feedback only when Coder needs to retry
        critic_feedback = ""
        llm_calls = 0
        if decision in ("retry", "fail"):
            critic_feedback = _generate_feedback(state, post, fix_score, decision, repo_path)
            llm_calls = 1

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
            "agent":         "critic",
            "timestamp":     datetime.utcnow().isoformat(),
            "input_fields":  ["patch", "changed_files", "broken_file"],
            "output_fields": ["test_results", "fix_score", "critic_feedback"],
            "llm_calls":     llm_calls,
            "tool_calls":    ["run_pytest", "run_linter", "run_shell"],
            "tests_passed":  tests_passed,
            "tests_failed":  tests_failed,
            "tests_before":  tests_before,
            "fix_score":     fix_score,
            "decision":      decision,
        })

    except Exception as e:
        logger.error(f"critic_agent failed: {e}", exc_info=True)
        state["error"] = f"critic_agent failed: {str(e)}"

    return state


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
        retry_count=state["retry_count"],
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


def _repo_path(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    owner, repo = parts[3], parts[4]
    return os.path.join("repos", f"{owner}__{repo}")
