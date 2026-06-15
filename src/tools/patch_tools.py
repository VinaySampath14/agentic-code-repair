import subprocess
import tempfile
import os


def apply_patch(patch: str, cwd: str) -> dict:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".diff", delete=False) as f:
        f.write(patch)
        patch_file = f.name

    try:
        # dry run first to validate
        dry = subprocess.run(
            f"git apply --check {patch_file}",
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if dry.returncode != 0:
            return {"success": False, "error": dry.stderr.strip()}

        # apply for real
        result = subprocess.run(
            f"git apply {patch_file}",
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr.strip()}

        return {"success": True, "error": None}
    finally:
        os.unlink(patch_file)


def validate_patch_syntax(patch: str) -> bool:
    lines = patch.splitlines()
    has_header = any(l.startswith("--- ") for l in lines)
    has_target = any(l.startswith("+++ ") for l in lines)
    has_hunk = any(l.startswith("@@") for l in lines)
    return has_header and has_target and has_hunk
