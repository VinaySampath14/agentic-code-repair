import json
import os
import subprocess


_FAST_TEST_FILES = [
    "tests/test_utils.py",
    "tests/test_structures.py",
    "tests/test_packages.py",
    "tests/test_help.py",
]


def run_pytest(cwd: str, test_path: str = "") -> dict:
    # Add src/ to PYTHONPATH so tests import the local patched version
    env = os.environ.copy()
    src_dir = os.path.join(os.path.abspath(cwd), "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{existing}" if existing else src_dir

    # Only run fast non-network tests when no path specified
    if not test_path:
        existing_files = [f for f in _FAST_TEST_FILES
                         if os.path.exists(os.path.join(cwd, f))]
        test_path = " ".join(existing_files) if existing_files else "tests/"

    result = subprocess.run(
        f"pytest {test_path} --tb=short -q",
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    # Try to parse plain pytest output for passed/failed counts
    stdout = result.stdout + result.stderr
    passed = 0
    failed = 0
    for line in stdout.splitlines():
        if " passed" in line or " failed" in line or " error" in line:
            parts = line.strip().split()
            for i, p in enumerate(parts):
                token = p.rstrip(",")  # strip trailing commas: "passed," → "passed"
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
