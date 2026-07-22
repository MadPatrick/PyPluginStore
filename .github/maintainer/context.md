# PyPluginStore Maintainer Context

PyPluginStore is a Domoticz Python plugin manager focused on reliable plugin discovery, installation, updates, and a custom UI for Linux-based Domoticz installations.

Priorities:
- Preserve remote registry loading with bundled fallback behavior.
- Keep `plugin_core.py` as the source for runtime logic and regenerate `plugin.py` after core edits.
- Avoid committing local runtime data such as `update_times.cache.json` or private registry overlays.
- Prefer a reviewed external PR as the source of its change when its intent,
  implementation, provenance, and validation are sound. Implement separately only
  when merging the PR is not viable, and record why.

Tone:
- Be direct and appreciative with contributors.
- Explain generated-file and registry behavior concretely because those areas have caused contributor friction.
