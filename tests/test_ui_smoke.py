from html.parser import HTMLParser
import json
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

    script = load_inline_script()

    result = subprocess.run(
        [node, "--check", "-"],
        input=script,
        capture_output=True,
        text=True,
    )
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

    result = subprocess.run(
        [node, "-"],
        input=node_script,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


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

    result = subprocess.run(
        [node, "-"],
        input=node_script,
        capture_output=True,
        text=True,
    )
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
