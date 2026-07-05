# Maintainer Patterns

- Generated runtime file: edit `plugin_core.py`, then run `python .github/scripts/generate_plugin.py`.
- Weekly registry discovery must require a non-empty root-level `plugin.py` before adding a repository; Domoticz-adjacent integrations, docs, Home Assistant bridges, MCP servers, scripts, and UI repos are not PyPluginStore plugins without that file.
- Git ownership repairs should prefer non-destructive, memory-only configuration overrides (`safe.directory` via `-c`) over disk-level permissions changes (`chown`), especially in Docker volume-mount environments, to avoid permission fights and file management friction on the host.
- Registry source order: remote public registry, bundled fallback, local ignored overlay.
- Installed detection is tiered: matching git remote, recognized `plugin.py` externallink, exact registry key, unique repo/archive folder name with flexible and Domoticz-affix-stripped normalization, then unique `plugin.py` key/name metadata.
- Local registry entries are explicit user intent and should win when they collide with public registry repository aliases.
- Keep plugin folder matching and UI plugin-name cleanup aligned. When changing flexible folder-name matching in the plugin, review/update the UI cleanup logic too, and vice versa, so the visible names users compare match the install-detection names PyPluginStore accepts.
- Custom UI bridge device discovery must include hidden Domoticz devices because users may hide the text payload device from normal overviews.
- The custom UI bridge shares one text device for request and response data; always clear stale responses and treat response-looking payloads as stale bridge data, not inbound commands.
- Domoticz Python plugin APIs vary across supported Domoticz versions; optional APIs such as native notifications must be guarded with `hasattr`/`callable` checks.
- Startup update checks must write their result to `self.update_status`; the custom UI only renders green update buttons from the cached status map.
- Runtime/local files should be ignored rather than committed when they contain host-specific state.
- Contributor PRs often include useful product intent with mechanical diff issues; preserve the intent and rework in a smaller local patch.
