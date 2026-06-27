import json
from pathlib import Path

from plugin_core_helpers import configure_home

def test_safe_plugin_dir_rejects_traversal(plugin_core_module, tmp_path):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()
    host = plugin.get_host()

    assert Path(host.resolve_plugin_dir("NormalPlugin")).name == "NormalPlugin"

    for bad_key in ("../outside", "..\\outside", ".hidden", ""):
        try:
            host.resolve_plugin_dir(bad_key)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad_key} should be rejected")


def test_remove_command_rejects_traversal(plugin_core_module, tmp_path):
    configure_home(plugin_core_module, tmp_path)
    plugin = plugin_core_module.BasePlugin()

    success, message = plugin.removePlugin("../outside")

    assert success is False
    assert "Invalid plugin key" in message


def test_windows_locked_remove_is_queued(plugin_core_module, tmp_path, monkeypatch):
    _, manager_dir = configure_home(plugin_core_module, tmp_path)
    plugin_dir = tmp_path / "domoticz" / "plugins" / "LockedPlugin"
    plugin_dir.mkdir()
    plugin = plugin_core_module.BasePlugin()
    plugin.host = plugin_core_module.WindowsHostRuntime(plugin_core_module.Parameters)

    monkeypatch.setattr(plugin_core_module.shutil, "rmtree", lambda path: (_ for _ in ()).throw(PermissionError("in use")))

    success, message = plugin.removePlugin("LockedPlugin")

    assert success is False
    assert "queued" in message
    assert json.loads((manager_dir / "pending_operations.json").read_text()) == [
        {"action": "remove", "plugin_key": "LockedPlugin"}
    ]
