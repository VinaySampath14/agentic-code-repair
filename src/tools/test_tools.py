import json
import os
import subprocess


_FAST_TEST_FILES: dict[str, list[str]] = {
    "psf__requests": [
        "tests/test_utils.py",
        "tests/test_structures.py",
        "tests/test_packages.py",
        "tests/test_help.py",
    ],
    "pylint-dev__pylint": [
        "tests/test_pragma_parser.py",
        "tests/test_config.py",
        "tests/lint/test_codeop.py",
        "tests/test_functional.py",
    ],
}


def _repo_key(cwd: str) -> str:
    """Derive owner__repo key from a repo_path like repos/psf__requests."""
    return os.path.basename(os.path.normpath(cwd))


def run_pytest(cwd: str, test_path: str = "") -> dict:
    env = os.environ.copy()
    src_dir = os.path.join(os.path.abspath(cwd), "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing}" if existing else src_dir

    if not test_path:
        repo_key = _repo_key(cwd)
        candidates = _FAST_TEST_FILES.get(repo_key, [])
        existing_files = [f for f in candidates if os.path.exists(os.path.join(cwd, f))]

        if existing_files:
            test_path = " ".join(existing_files)
        else:
            # Unknown repo — run tests/ but stop on first failure and cap per-test time
            test_path = "tests/ -x --timeout=30" if os.path.isdir(os.path.join(cwd, "tests")) else "."

    result = subprocess.run(
        f"pytest {test_path} --tb=short -q",
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    stdout = result.stdout + result.stderr
    passed = 0
    failed = 0
    for line in stdout.splitlines():
        if " passed" in line or " failed" in line or " error" in line:
            parts = line.strip().split()
            for i, p in enumerate(parts):
                token = p.rstrip(",")
                if token == "passed" and i > 0:
                    try:
                        passed = int(parts[i - 1])
                    except ValueError:
                        pass
                if token in ("failed", "error") and i > 0:
                    try:
                        failed += int(parts[i - 1])
                    except ValueError:
                        pass

    return {
        "passed": passed,
        "failed": failed,
        "errors": 0,
        "total": passed + failed,
        "raw": stdout[:2000],
    }


def run_linter(cwd: str, path: str = "src/") -> dict:
    result = subprocess.run(
        f"ruff check {path} --output-format=json",
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    try:
        issues = json.loads(result.stdout)
        return {"issue_count": len(issues), "issues": issues}
    except json.JSONDecodeError:
        return {"issue_count": 0, "issues": []}
