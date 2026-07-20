import sys
import types

from conftest import REPO_ROOT, load_module_from_path


def test_restored_plugin_normalizes_object_registry_entries(monkeypatch):
    monkeypatch.setitem(sys.modules, "Domoticz", types.ModuleType("Domoticz"))
    module = load_module_from_path(
        "plugin_restored_registry_under_test",
        REPO_ROOT / "plugin_restored.py",
    )
    legacy_entry = ["legacy-owner", "legacy-repo", "Legacy", "master"]

    normalized = module.BasePlugin().normalize_registry_data(
        {
            "ObjectPlugin": {
                "owner": "gitlab.com/group/subgroup",
                "repository": "object-plugin",
                "description": "Object entry",
                "branch": "main",
                "platforms": ["linux"],
            },
            "LegacyPlugin": legacy_entry,
        }
    )

    assert normalized["ObjectPlugin"] == [
        "gitlab.com/group/subgroup",
        "object-plugin",
        "Object entry",
        "main",
        "",
        ["linux"],
    ]
    assert normalized["LegacyPlugin"] == legacy_entry
