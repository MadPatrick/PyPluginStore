def configure_home(plugin_core_module, tmp_path):
    plugins_dir = tmp_path / "domoticz" / "plugins"
    manager_dir = plugins_dir / "00-PyPluginStore"
    manager_dir.mkdir(parents=True)
    write_plugin_py(
        manager_dir,
        key="PP-MANAGER",
        name="PyPluginStore",
        externallink="https://github.com/adrighem/PyPluginStore",
    )
    plugin_core_module.Parameters = {
        "HomeFolder": str(manager_dir) + "/",
        "Mode4": "None",
        "Mode6": "Normal",
    }
    return plugins_dir, manager_dir


def write_plugin_py(plugin_dir, key, name, externallink=""):
    plugin_dir.mkdir(parents=True, exist_ok=True)
    externallink_attr = f' externallink="{externallink}"' if externallink else ""
    (plugin_dir / "plugin.py").write_text(
        f'"""\n<plugin key="{key}" name="{name}" author="tester"{externallink_attr}>\n</plugin>\n"""\n'
    )


def debug_messages(plugin_core_module):
    return [args[0] for args, _ in plugin_core_module.Domoticz.calls["Debug"] if args]
