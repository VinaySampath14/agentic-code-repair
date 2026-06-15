import subprocess
import json


def run_pytest(cwd: str, test_path: str = ".") -> dict:
    result = subprocess.run(
        f"pytest {test_path} --tb=short -q --json-report --json-report-file=-",
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    try:
        report = json.loads(result.stdout)
        summary = report.get("summary", {})
        return {
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
            "errors": summary.get("error", 0),
            "total": summary.get("total", 0),
        }
    except (json.JSONDecodeError, KeyError):
        # fallback: parse plain pytest output
        passed = result.stdout.count(" passed")
        failed = result.stdout.count(" failed")
        return {
            "passed": passed,
            "failed": failed,
            "errors": 0,
            "total": passed + failed,
            "raw": result.stdout,
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
