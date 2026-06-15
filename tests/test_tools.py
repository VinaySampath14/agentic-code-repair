import pytest
from src.tools.shell_tools import run_shell, get_imports
from src.tools.patch_tools import validate_patch_syntax


def test_run_shell_success():
    result = run_shell("echo hello")
    assert result["returncode"] == 0
    assert "hello" in result["stdout"]


def test_run_shell_timeout():
    result = run_shell("ping -n 5 127.0.0.1", timeout=1)
    assert result["returncode"] == -1
    assert "timed out" in result["stderr"]


def test_get_imports():
    code = "import os\nfrom pathlib import Path\nx = 1"
    imports = get_imports(code)
    assert "import os" in imports
    assert "from pathlib import Path" in imports
    assert len(imports) == 2


def test_validate_patch_syntax_valid():
    patch = (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-old line\n"
        "+new line\n"
    )
    assert validate_patch_syntax(patch) is True


def test_validate_patch_syntax_invalid():
    assert validate_patch_syntax("not a patch") is False
