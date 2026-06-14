import re
import shutil
import subprocess

import pytest

from conftest import REPO_ROOT


def test_pypluginstore_javascript_has_valid_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    html = (REPO_ROOT / "pypluginstore.html").read_text()
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert match, "pypluginstore.html does not contain an inline script"

    result = subprocess.run(
        [node, "--check", "-"],
        input=match.group(1),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
