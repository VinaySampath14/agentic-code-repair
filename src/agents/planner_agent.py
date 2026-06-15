import json
import logging
import os
import subprocess
from datetime import datetime
from openai import OpenAI
from src.state import AgentState

logger = logging.getLogger(__name__)
from src.config import ACTIVE_MODEL
from src.tools.github_tools import get_repo_structure, search_codebase

_client = OpenAI(api_key=ACTIVE_MODEL["api_key"], base_url=ACTIVE_MODEL["base_url"], timeout=60.0)


def planner_agent(state: AgentState) -> AgentState:
    try:
        repo_full_name = _parse_repo(state["issue_url"])
        repo_path = _repo_path(state["issue_url"])

        # Ensure local clone exists (used as fallback for repo structure)
        if not os.path.isdir(repo_path):
            parts = state["issue_url"].rstrip("/").split("/")
            clone_url = f"https://github.com/{parts[3]}/{parts[4]}.git"
            os.makedirs("repos", exist_ok=True)
            logger.info(f"cloning {clone_url} for repo structure")
            subprocess.run(f"git clone {clone_url} {repo_path}", shell=True,
                           capture_output=True, timeout=300)

        logger.info(f"fetching repo structure for {repo_full_name}")
        try:
            repo_structure = get_repo_structure(repo_full_name)
        except Exception as e:
            logger.warning(f"GitHub API failed for repo structure ({type(e).__name__}) — using local clone")
            repo_structure = _local_repo_structure(repo_path)

        logger.info("searching codebase")
        try:
            search_results = search_codebase(
                repo_full_name,
                state["issue_body"][:200]
            )
            logger.info(f"search_codebase returned {len(search_results)} results")
        except Exception as e:
            logger.warning(f"search_codebase failed (non-fatal): {type(e).__name__}: {e}")
            search_results = []

        prompt_template = open("prompts/planner.txt").read()
        prompt = prompt_template.format(
            issue_url=state["issue_url"],
            issue_body=state["issue_body"],
            repo_structure=repo_structure,
            search_results=search_results,
        )

        logger.info("calling OpenAI")
        response = _client.chat.completions.create(
            model=ACTIVE_MODEL["model"],
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=30.0,
        )

        raw = response.choices[0].message.content
        result = json.loads(raw)

        _validate(result, ["core_problem", "affected_files", "complexity", "confidence"])

        state["core_problem"] = result["core_problem"]
        state["affected_files"] = result["affected_files"]
        state["complexity"] = result["complexity"]
        state["planner_confidence"] = result["confidence"]
        logger.info(f"done — {len(result['affected_files'])} files, confidence={result['confidence']}")

        state["trace"].append({
            "agent":         "planner",
            "timestamp":     datetime.utcnow().isoformat(),
            "input_fields":  ["issue_body", "issue_url"],
            "output_fields": ["affected_files", "core_problem", "complexity", "planner_confidence"],
            "llm_calls":     1,
            "tool_calls":    ["get_repo_structure", "search_codebase"],
            "confidence":    state["planner_confidence"],
        })

    except Exception as e:
        logger.error(f"planner_agent failed: {e}", exc_info=True)
        state["error"] = f"planner_agent failed: {str(e)}"

    return state


def _parse_repo(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    return f"{parts[3]}/{parts[4]}"


def _repo_path(issue_url: str) -> str:
    parts = issue_url.rstrip("/").split("/")
    return os.path.join("repos", f"{parts[3]}__{parts[4]}")


def _local_repo_structure(repo_path: str) -> str:
    lines = []
    for root, dirs, files in os.walk(repo_path):
        # Skip hidden dirs and __pycache__
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        rel_root = os.path.relpath(root, repo_path).replace("\\", "/")
        for f in files:
            path = f"{rel_root}/{f}" if rel_root != "." else f
            lines.append(path)
    logger.info(f"local repo structure: {len(lines)} entries")
    return "\n".join(lines)


def _validate(data: dict, required: list[str]) -> None:
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"LLM response missing fields: {missing}")
