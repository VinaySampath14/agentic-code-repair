import json
import os
import re
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
        "tests/test_numversion.py",
        "tests/test_similar.py",
        "tests/test_func.py",
    ],
}

# Repos that use a custom test runner instead of pytest.
# Value is the command template; {modules} is replaced with space-separated module names.
_CUSTOM_RUNNER: dict[str, dict] = {
    "django__django": {
        "cmd": "python tests/runtests.py {modules} --verbosity=0",
        "modules": [
            "utils_tests.test_text",
            "utils_tests.test_functional",
            "utils_tests.test_encoding",
        ],
        "parse": "django",
    },
}


def _repo_key(cwd: str) -> str:
    return os.path.basename(os.path.normpath(cwd))


def run_pytest(cwd: str, test_path: str = "") -> dict:
    repo_key = _repo_key(cwd)

    # Django uses its own test runner — derive module from test_path node IDs if provided
    if repo_key in _CUSTOM_RUNNER:
        if test_path:
            return _run_custom_with_ids(cwd, repo_key, test_path)
        return _run_custom(cwd, repo_key)

    env = os.environ.copy()
    cwd_abs = os.path.abspath(cwd)
    src_dir = os.path.join(cwd_abs, "src")
    existing = env.get("PYTHONPATH", "")
    # Add both repo root (flat layout: astropy/, xarray/) and src/ (src layout: src/flask/)
    extra = f"{cwd_abs}{os.pathsep}{src_dir}"
    env["PYTHONPATH"] = f"{extra}{os.pathsep}{existing}" if existing else extra

    if not test_path:
        candidates = _FAST_TEST_FILES.get(repo_key, [])
        existing_files = [f for f in candidates if os.path.exists(os.path.join(cwd, f))]
        if existing_files:
            test_path = " ".join(existing_files)
        else:
            test_path = "tests/ -x --timeout=30" if os.path.isdir(os.path.join(cwd, "tests")) else "."

    result = subprocess.run(
        f"pytest {test_path} --tb=short -q",
        shell=True, cwd=cwd, capture_output=True, text=True, timeout=120, env=env,
    )

    stdout = result.stdout + result.stderr
    return _parse_pytest_output(stdout)


def _run_custom_with_ids(cwd: str, repo_key: str, test_path: str) -> dict:
    """Run Django's runtests.py with modules derived from SWE-bench test node IDs.

    Node IDs look like: tests/auth_tests/test_basic.py::Class::method
    Django runtests.py wants:            auth_tests.test_basic
    """
    modules: list[str] = []
    seen: set[str] = set()
    for node_id in test_path.split():
        file_part = node_id.split("::")[0]  # tests/auth_tests/test_basic.py
        # Strip leading "tests/" and ".py" suffix, convert "/" to "."
        rel = file_part.removeprefix("tests/").removesuffix(".py").replace("/", ".")
        if rel and rel not in seen:
            modules.append(rel)
            seen.add(rel)
    if not modules:
        return _run_custom(cwd, repo_key)
    cfg = _CUSTOM_RUNNER[repo_key]
    cmd = cfg["cmd"].format(modules=" ".join(modules))
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120,
    )
    return _parse_django_output(result.stdout + result.stderr)


def _run_custom(cwd: str, repo_key: str) -> dict:
    cfg = _CUSTOM_RUNNER[repo_key]
    modules = " ".join(cfg["modules"])
    cmd = cfg["cmd"].format(modules=modules)

    result = subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120,
    )
    stdout = result.stdout + result.stderr

    if cfg["parse"] == "django":
        return _parse_django_output(stdout)
    return _parse_pytest_output(stdout)


def _parse_pytest_output(stdout: str) -> dict:
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
    return {"passed": passed, "failed": failed, "errors": 0,
            "total": passed + failed, "raw": stdout[:2000]}


def _parse_django_output(stdout: str) -> dict:
    # Django runtests.py outputs "Ran X tests in Ys" and "OK" or "FAILED (failures=N)"
    passed = 0
    failed = 0
    for line in stdout.splitlines():
        m = re.search(r"Ran (\d+) test", line)
        if m:
            total = int(m.group(1))
            fail_m = re.search(r"FAILED.*failures=(\d+)", stdout)
            error_m = re.search(r"FAILED.*errors=(\d+)", stdout)
            failed = int(fail_m.group(1)) if fail_m else 0
            failed += int(error_m.group(1)) if error_m else 0
            passed = total - failed
            break
    return {"passed": passed, "failed": failed, "errors": 0,
            "total": passed + failed, "raw": stdout[:2000]}


def run_linter(cwd: str, path: str = "src/") -> dict:
    result = subprocess.run(
        f"ruff check {path} --output-format=json",
        shell=True, cwd=cwd, capture_output=True, text=True,
    )
    try:
        issues = json.loads(result.stdout)
        return {"issue_count": len(issues), "issues": issues}
    except json.JSONDecodeError:
        return {"issue_count": 0, "issues": []}
