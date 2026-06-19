from typing import TypedDict
from datetime import datetime


class AgentState(TypedDict):
    # input
    issue_url:           str
    issue_body:          str
    instance_id:         str

    # planner output
    affected_files:      list[str]
    core_problem:        str
    complexity:          int
    planner_confidence:  str

    # explorer output
    file_contents:       dict[str, str]
    broken_function:     str
    broken_file:         str
    current_behaviour:   str
    expected_behaviour:  str
    explorer_confidence: str

    # coder output
    patch:               str
    changed_files:       list[str]
    change_description:  str

    # critic output
    test_results:        dict
    fix_score:           float
    critic_feedback:     str

    # pr agent output
    pr_url:              str

    # control
    retry_count:         int
    trace:               list[dict]
    error:               str | None
    eval_mode:           bool
    quick_mode:          bool
    fail_to_pass:        list[str]


def initial_state(
    issue_url:    str,
    issue_body:   str,
    instance_id:  str,
    eval_mode:    bool = False,
    quick_mode:   bool = False,
    fail_to_pass: list[str] | None = None,
) -> AgentState:
    return AgentState(
        issue_url=issue_url,
        issue_body=issue_body,
        instance_id=instance_id,
        eval_mode=eval_mode,
        quick_mode=quick_mode,
        fail_to_pass=fail_to_pass or [],
        affected_files=[],
        core_problem="",
        complexity=0,
        planner_confidence="",
        file_contents={},
        broken_function="",
        broken_file="",
        current_behaviour="",
        expected_behaviour="",
        explorer_confidence="",
        patch="",
        changed_files=[],
        change_description="",
        test_results={},
        fix_score=0.0,
        critic_feedback="",
        pr_url="",
        retry_count=0,
        trace=[],
        error=None,
    )
