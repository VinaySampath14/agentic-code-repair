"""
Smoke tests — catch import errors, NameErrors, and broken agent signatures
before running a full eval. Each test mounts a minimal fake state and verifies
the agent returns without raising an unhandled exception.

Run with: pytest tests/test_agents_smoke.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from src.state import initial_state


def _base_state(**overrides):
    s = initial_state(
        issue_url="https://github.com/psf/requests/issues/1734",
        issue_body="Test issue body describing a bug.",
        instance_id="psf__requests-1734",
        eval_mode=True,
        fail_to_pass=["tests/test_utils.py::TestUtils::test_foo"],
    )
    s.update(overrides)
    return s


# ---------------------------------------------------------------------------
# Import smoke tests — fail immediately if any agent has a broken import
# ---------------------------------------------------------------------------

def test_import_planner():
    from src.agents.planner_agent import planner_agent
    assert callable(planner_agent)

def test_import_explorer():
    from src.agents.explorer_agent import explorer_agent
    assert callable(explorer_agent)

def test_import_coder():
    from src.agents.coder_agent import coder_agent
    assert callable(coder_agent)

def test_import_critic():
    from src.agents.critic_agent import critic_agent
    assert callable(critic_agent)

def test_import_pr_agent():
    from src.agents.pr_agent import pr_agent
    assert callable(pr_agent)


# ---------------------------------------------------------------------------
# critic_agent unit test — the source of most scoring bugs
# ---------------------------------------------------------------------------

def test_critic_no_patch_returns_zero():
    """Critic must return fix_score=0.0 and not crash when patch is empty."""
    from src.agents.critic_agent import critic_agent
    import os
    state = _base_state(patch="", broken_file="requests/utils.py")
    # Critic checks if repo dir exists — fake it
    with patch("os.path.isdir", return_value=True):
        result = critic_agent(state)
    assert result["fix_score"] == 0.0
    assert result.get("error") is None or "no patch" in (result.get("critic_feedback") or "").lower()


def test_critic_score_variables_always_defined():
    """test_pass_rate and no_regression must never cause NameError."""
    from src.agents.critic_agent import critic_agent

    state = _base_state(
        patch="--- a/requests/utils.py\n+++ b/requests/utils.py\n@@ -1 +1 @@\n-old\n+new\n",
        broken_file="requests/utils.py",
        broken_function="some_func",
        changed_files=["requests/utils.py"],
        change_description="fix bug",
    )

    # Simulate: tests return 0 collected (the common case that triggered the NameError)
    zero_tests = {"passed": 0, "failed": 0, "total": 0, "raw": "no tests ran"}

    with patch("os.path.isdir", return_value=True), \
         patch("src.agents.critic_agent.run_pytest", return_value=zero_tests), \
         patch("src.agents.critic_agent.run_shell", return_value={"returncode": 0, "stdout": "", "stderr": ""}), \
         patch("src.agents.critic_agent._llm_score_patch", return_value=0.75), \
         patch("src.agents.critic_agent._generate_feedback", return_value="try again"), \
         patch("src.agents.critic_agent.run_linter", return_value={"issue_count": 0}):
        result = critic_agent(state)

    assert "fix_score" in result
    assert isinstance(result["fix_score"], float)
    assert result.get("error") is None, f"unexpected error: {result.get('error')}"


def test_critic_score_with_passing_tests():
    """When tests pass, fix_score should use the test-based formula."""
    from src.agents.critic_agent import critic_agent

    state = _base_state(
        patch="--- a/requests/utils.py\n+++ b/requests/utils.py\n@@ -1 +1 @@\n-old\n+new\n",
        broken_file="requests/utils.py",
        broken_function="some_func",
        changed_files=["requests/utils.py"],
        change_description="fix bug",
    )

    passing = {"passed": 5, "failed": 0, "total": 5, "raw": "5 passed"}

    with patch("os.path.isdir", return_value=True), \
         patch("src.agents.critic_agent.run_pytest", return_value=passing), \
         patch("src.agents.critic_agent.run_shell", return_value={"returncode": 0, "stdout": "", "stderr": ""}), \
         patch("src.agents.critic_agent._semantic_check", return_value={"addresses_root_cause": True}), \
         patch("src.agents.critic_agent.run_linter", return_value={"issue_count": 0}):
        result = critic_agent(state)

    # 5 passed, 0 failed, baseline 5: test_pass_rate=1.0, no_regression=1.0, quality=1.0 → 1.0
    assert result["fix_score"] == 1.0
    assert result.get("error") is None


# ---------------------------------------------------------------------------
# Tracing shim smoke test
# ---------------------------------------------------------------------------

def test_tracing_shim_always_importable():
    """tracing.py must import and expose OpenAI + observe regardless of env vars."""
    from src.tracing import OpenAI, observe, langfuse_context
    assert callable(OpenAI)
    assert callable(observe)
    # langfuse_context is None when keys are absent/placeholder — that's fine
