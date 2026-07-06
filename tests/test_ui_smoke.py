from html.parser import HTMLParser
import json
import os
import shutil
import subprocess
import tempfile

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

    script = load_inline_script()
    mocks = """
    const noop = () => {};
    const document = {
        readyState: 'complete',
        getElementById: () => ({ addEventListener: noop, onclick: null }),
        addEventListener: noop
    };
    const window = {
        document,
        addEventListener: noop
    };
    const alert = noop;
    const location = {};
    const fetch = noop;
    const setTimeout = noop;
    """

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write(mocks + script)
        temp_path = f.name
    try:
        result = subprocess.run(
            [node, "--check", temp_path],
            capture_output=True,
            text=True,
        )
    finally:
        os.remove(temp_path)
    assert result.returncode == 0, result.stderr


def test_plugin_display_name_strips_domoticz_affixes():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    function_source = extract_js_function(load_inline_script(), "formatPluginDisplayName")
    cases = {
        "Domoticz-AWTRIX3-Plugin": "AWTRIX3-Plugin",
        "domoticz-for-HomeWizard": "HomeWizard",
        "Domoticz for Solar": "Solar",
        "domoticz_plugin_HomeWizard": "HomeWizard",
        "domoticz plugin Solar": "Solar",
        "Broadlink-Domoticz-plugin": "Broadlink",
        "Pollen-forecast-in-Norway-for-Domoticz": "Pollen-forecast-in-Norway",
        "Forecast_for_domoticz": "Forecast",
        "DomoticzTile": "DomoticzTile",
        "PluginDomoticzFreebox": "PluginDomoticzFreebox",
    }
    node_script = f"""
{function_source}
const cases = {json.dumps(cases)};
for (const [input, expected] of Object.entries(cases)) {{
    const actual = formatPluginDisplayName(input);
    if (actual !== expected) {{
        throw new Error(`${{input}}: expected "${{expected}}", got "${{actual}}"`);
    }}
}}
"""

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write(node_script)
        temp_path = f.name
    try:
        result = subprocess.run(
            [node, temp_path],
            capture_output=True,
            text=True,
        )
    finally:
        os.remove(temp_path)
    assert result.returncode == 0, result.stderr


def test_repo_url_builder_supports_codeberg_and_gitlab_hosts():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    script = load_inline_script()
    function_source = "\n".join([
        extract_js_function(script, "stripRepoUrl"),
        extract_js_function(script, "encodeRepoPath"),
        extract_js_function(script, "encodeBranchPath"),
        extract_js_function(script, "parseRepoReference"),
        extract_js_function(script, "buildRepoUrl"),
    ])
    cases = [
        ["owner", "repo", "https://github.com/owner/repo"],
        ["github.com/Hoog", "Domoticz-Stromer-plugin", "https://github.com/Hoog/Domoticz-Stromer-plugin"],
        ["codeberg.org/Hoog", "Domoticz-Stromer-plugin", "https://codeberg.org/Hoog/Domoticz-Stromer-plugin"],
        ["gitlab.com/r.boeters", "DomoticzSabNZBDPlugin", "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin"],
        ["example.org/Team", "DomoticzPlugin", "https://example.org/Team/DomoticzPlugin"],
        ["git@gitlab.com:r.boeters/DomoticzSabNZBDPlugin.git", "", "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin"],
        ["git@example.org:Team/DomoticzPlugin.git", "", "https://example.org/Team/DomoticzPlugin"],
        ["https://codeberg.org/Hoog/Domoticz-Stromer-plugin/src/branch/main", "", "https://codeberg.org/Hoog/Domoticz-Stromer-plugin"],
        ["https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin/-/tree/master", "", "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin"],
        ["owner", "repo", "https://github.com/owner/repo/tree/feature/meters", "feature/meters"],
        ["codeberg.org/Hoog", "Domoticz-Stromer-plugin", "https://codeberg.org/Hoog/Domoticz-Stromer-plugin/src/branch/main", "main"],
        ["gitlab.com/r.boeters", "DomoticzSabNZBDPlugin", "https://gitlab.com/r.boeters/DomoticzSabNZBDPlugin/-/tree/release/2.0", "release/2.0"],
        ["example.org/Team", "DomoticzPlugin", "https://example.org/Team/DomoticzPlugin", "main"],
    ]
    node_script = f"""
{function_source}
const cases = {json.dumps(cases)};
for (const [author, repo, expected, branch] of cases) {{
    const actual = buildRepoUrl(author, repo, branch);
    if (actual !== expected) {{
        throw new Error(`${{author}}/${{repo}}: expected "${{expected}}", got "${{actual}}"`);
    }}
}}
"""

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write(node_script)
        temp_path = f.name
    try:
        result = subprocess.run(
            [node, temp_path],
            capture_output=True,
            text=True,
        )
    finally:
        os.remove(temp_path)
    assert result.returncode == 0, result.stderr


def test_version_status_uses_remote_label_when_installed_is_newer():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    script = load_inline_script()
    function_source = "\n".join([
        extract_js_function(script, "parseVersionParts"),
        extract_js_function(script, "compareVersions"),
        extract_js_function(script, "formatVersionStatus"),
    ])
    node_script = f"""
{function_source}
const olderRemote = formatVersionStatus({{installed: '2.0.5.5', available: '2.0.4'}}, 'available');
if (olderRemote !== 'Installed: v2.0.5.5 | Remote: v2.0.4 (installed is newer)') {{
    throw new Error(`Unexpected older remote status: ${{olderRemote}}`);
}}
const newerRemote = formatVersionStatus({{installed: '1.0.0', available: '2.0.0'}}, 'available');
if (newerRemote !== 'Installed: v1.0.0 | Available: v2.0.0') {{
    throw new Error(`Unexpected newer remote status: ${{newerRemote}}`);
}}
"""

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write(node_script)
        temp_path = f.name
    try:
        result = subprocess.run(
            [node, temp_path],
            capture_output=True,
            text=True,
        )
    finally:
        os.remove(temp_path)
    assert result.returncode == 0, result.stderr


def test_author_display_includes_repository_host_for_all_hosted_entries():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    script = load_inline_script()
    function_source = "\n".join([
        extract_js_function(script, "stripRepoUrl"),
        extract_js_function(script, "encodeRepoPath"),
        extract_js_function(script, "parseRepoReference"),
        extract_js_function(script, "formatAuthorDisplay"),
    ])
    cases = [
        ["Hoog", "Domoticz-Stromer-plugin", "github.com/Hoog"],
        ["github.com/Hoog", "Domoticz-Stromer-plugin", "github.com/Hoog"],
        ["codeberg.org/Hoog", "Domoticz-Stromer-plugin", "codeberg.org/Hoog"],
        ["gitlab.com/r.boeters", "DomoticzSabNZBDPlugin", "gitlab.com/r.boeters"],
        ["https://codeberg.org/Hoog/Domoticz-Stromer-plugin/src/branch/main", "", "codeberg.org/Hoog"],
        ["git@gitlab.com:r.boeters/DomoticzSabNZBDPlugin.git", "", "gitlab.com/r.boeters"],
    ]
    node_script = f"""
{function_source}
const cases = {json.dumps(cases)};
for (const [author, repo, expected] of cases) {{
    const actual = formatAuthorDisplay(author, repo);
    if (actual !== expected) {{
        throw new Error(`${{author}}/${{repo}}: expected "${{expected}}", got "${{actual}}"`);
    }}
}}
"""

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write(node_script)
        temp_path = f.name
    try:
        result = subprocess.run(
            [node, temp_path],
            capture_output=True,
            text=True,
        )
    finally:
        os.remove(temp_path)
    assert result.returncode == 0, result.stderr


def test_plugin_cards_use_formatted_author_display():
    script = load_inline_script()

    assert "'Author: ' + formatAuthorDisplay(author, repo)" in script
    assert "'Author: ' + author" not in script


def test_update_buttons_keep_shared_and_state_specific_classes():
    html = (REPO_ROOT / "pypluginstore.html").read_text()

    assert ".btn-update {" in html
    assert ".btn-update-available {" in html
    assert ".btn-update-current {" in html
    assert "btn-update btn-update-available" in html
    assert "btn-update btn-update-current" in html


def test_refresh_status_button_is_wired_to_backend_command():
    html = (REPO_ROOT / "pypluginstore.html").read_text()
    script = load_inline_script()

    assert 'id="refresh-update-status"' in html
    assert "document.getElementById('refresh-update-status').onclick = refreshUpdateStatus" in script
    assert "sendCommand('refresh_update_status', {})" in script


def test_api_bridge_lookup_includes_hidden_and_unused_devices():
    script = load_inline_script()

    assert "filter=all&used=all&displayhidden=1" in script
    assert "used=true&displayhidden=1" in script
    assert "filter=all&used=all" in script
    assert "getdevices&' + query" in script


def test_api_bridge_payload_is_cleared_around_commands():
    script = load_inline_script()

    assert "async function clearApiBridgePayload()" in script
    assert "await clearApiBridgePayload();" in script
    assert "Could not clear API bridge payload" in script


def test_api_bridge_accepts_error_response_without_action():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    poll_response_source = extract_js_function(load_inline_script(), "pollResponse")
    node_script = f"""
const payloadIdx = 1;
let clearCalls = 0;
const setTimeout = (resolve, delay) => resolve();
const fetch = async () => ({{
    json: async () => ({{
        result: [{{
            Data: JSON.stringify({{
                status: 'error',
                tx_id: 'tx-123',
                message: 'preflight failed'
            }})
        }}]
    }})
}});
async function clearApiBridgePayload() {{
    clearCalls += 1;
}}

{poll_response_source}

(async () => {{
    const response = await pollResponse('update', 'tx-123', 1);
    if (response.status !== 'error' || response.message !== 'preflight failed') {{
        throw new Error('missing-action error response was not returned');
    }}
    if (clearCalls !== 1) {{
        throw new Error(`expected clearApiBridgePayload once, got ${{clearCalls}}`);
    }}
}})().catch(error => {{
    console.error(error);
    process.exit(1);
}});
"""

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write(node_script)
        temp_path = f.name
    try:
        result = subprocess.run(
            [node, temp_path],
            capture_output=True,
            text=True,
        )
    finally:
        os.remove(temp_path)
    assert result.returncode == 0, result.stderr


def test_self_update_does_not_reload_plugin_list_immediately():
    script = load_inline_script()

    assert "const successMessage = response.message" in script
    assert "action === 'update' && pluginKey === managerKey" in script


def test_installed_filter_state_is_persisted_in_local_storage():
    script = load_inline_script()

    assert "INSTALLED_FILTER_STORAGE_KEY = 'pypluginstore.installedOnly'" in script
    assert "readStoredInstalledFilter()" in script
    assert "writeStoredInstalledFilter(installedToggle.checked)" in script
    assert "installedToggle.checked = readStoredInstalledFilter()" in script
    assert ".localStorage.getItem(INSTALLED_FILTER_STORAGE_KEY)" in script
    assert ".localStorage.setItem(INSTALLED_FILTER_STORAGE_KEY" in script


def test_installed_filter_storage_helpers_are_tolerant():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    script = load_inline_script()
    read_function = extract_js_function(script, "readStoredInstalledFilter")
    write_function = extract_js_function(script, "writeStoredInstalledFilter")
    node_script = f"""
const INSTALLED_FILTER_STORAGE_KEY = 'pypluginstore.installedOnly';
{read_function}
{write_function}

const values = {{}};
global.window = {{
    localStorage: {{
        getItem: key => values[key] || null,
        setItem: (key, value) => values[key] = value,
    }}
}};

if (readStoredInstalledFilter() !== false) {{
    throw new Error('default installed filter state should be false');
}}

writeStoredInstalledFilter(true);
if (values[INSTALLED_FILTER_STORAGE_KEY] !== 'true') {{
    throw new Error('true state was not stored');
}}
if (readStoredInstalledFilter() !== true) {{
    throw new Error('true state was not restored');
}}

writeStoredInstalledFilter(false);
if (values[INSTALLED_FILTER_STORAGE_KEY] !== 'false') {{
    throw new Error('false state was not stored');
}}
if (readStoredInstalledFilter() !== false) {{
    throw new Error('false state was not restored');
}}

global.window = {{
    localStorage: {{
        getItem: () => {{ throw new Error('storage unavailable'); }},
        setItem: () => {{ throw new Error('storage unavailable'); }},
    }}
}};

if (readStoredInstalledFilter() !== false) {{
    throw new Error('unavailable storage should fall back to false');
}}
writeStoredInstalledFilter(true);
"""

    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write(node_script)
        temp_path = f.name
    try:
        result = subprocess.run(
            [node, temp_path],
            capture_output=True,
            text=True,
        )
    finally:
        os.remove(temp_path)
    assert result.returncode == 0, result.stderr


def test_platform_badges_are_wired_to_backend_response():
    html = (REPO_ROOT / "pypluginstore.html").read_text()
    script = load_inline_script()

    assert ".platform-badge-linux" in html
    assert ".platform-badge-windows" in html
    assert "platformCache = response.platforms || {}" in script
    assert "platform-badge platform-badge-" in script


def test_custom_ui_references_existing_icon_asset():
    html = (REPO_ROOT / "pypluginstore.html").read_text()

    assert 'src="images/pypluginstore-icon.png"' in html
    assert "this.src = '/images/pypluginstore-icon.png'" in html
    assert (REPO_ROOT / "pypluginstore-icon.png").is_file()


def load_inline_script():
    html = (REPO_ROOT / "pypluginstore.html").read_text()
    parser = InlineScriptParser()
    parser.feed(html)
    assert parser.scripts, "pypluginstore.html does not contain an inline script"
    return parser.scripts[0]


def extract_js_function(script, function_name):
    start = script.index(f"function {function_name}")
    async_prefix = "async "
    prefix_start = start - len(async_prefix)
    if prefix_start >= 0 and script[prefix_start:start] == async_prefix:
        start = prefix_start
    brace_start = script.index("{", start)
    depth = 0
    for index in range(brace_start, len(script)):
        if script[index] == "{":
            depth += 1
        elif script[index] == "}":
            depth -= 1
            if depth == 0:
                return script[start:index + 1]

    raise AssertionError(f"Function {function_name} was not closed")
