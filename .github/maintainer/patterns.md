# Maintainer Patterns

- Generated runtime file: edit `plugin_core.py`, then run `python .github/scripts/generate_plugin.py`.
- Registry source order: remote public registry, bundled fallback, local ignored overlay.
- Installed detection is tiered: matching git remote, recognized `plugin.py` externallink, exact registry key, unique repo/archive folder name with flexible and Domoticz-affix-stripped normalization, then unique `plugin.py` key/name metadata.
- Keep plugin folder matching and UI plugin-name cleanup aligned. When changing flexible folder-name matching in the plugin, review/update the UI cleanup logic too, and vice versa, so the visible names users compare match the install-detection names PyPluginStore accepts.
- Runtime/local files should be ignored rather than committed when they contain host-specific state.
- Contributor PRs often include useful product intent with mechanical diff issues; preserve the intent and rework in a smaller local patch.
