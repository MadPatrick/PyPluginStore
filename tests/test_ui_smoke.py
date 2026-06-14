from html.parser import HTMLParser
import shutil
import subprocess

import pytest

from conftest import REPO_ROOT


class InlineScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_script = False
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self._in_script = True
            self.scripts.append("")

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.scripts[-1] += data


def test_pypluginstore_javascript_has_valid_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    html = (REPO_ROOT / "pypluginstore.html").read_text()
    parser = InlineScriptParser()
    parser.feed(html)
    assert parser.scripts, "pypluginstore.html does not contain an inline script"

    result = subprocess.run(
        [node, "--check", "-"],
        input=parser.scripts[0],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
