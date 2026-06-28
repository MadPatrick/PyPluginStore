# ISSUE:60 - API Payload length log

Status: open; fix committed locally as `66ae709`.

Reporter:
- `Eddie-BS` reported this Domoticz log line on 2026-06-28:
  `Error: PyPluginStore: API Payload exceeds length limit.`

Intent:
- Stop the custom UI bridge from logging an error when the shared text device still contains PyPluginStore's own large response.
- Preserve the inbound command payload-size guard for actual oversized requests.

Assessment:
- The UI bridge uses the same Domoticz text device for browser-to-plugin requests and plugin-to-browser responses.
- `list_plugins` and `refresh_update_status` responses include the full registry, installed state, update status, and platform metadata, so the response can be much larger than the 2000-character command guard.
- On the next trigger, the plugin can see the previous large response in `Devices[1].sValue` before the next small request is visible, then logs `API Payload exceeds length limit.`
- This is likely to become more visible as the registry grows; the current bundled registry has 326 plugins.

Local fix:
- Empty API payload values are ignored instead of parsed as invalid JSON.
- Oversized values that look like stale API responses are cleared and ignored without an error.
- The stale-response detector also handles truncated response strings that start with a response `status` field.
- True oversized inbound requests still log `API Payload exceeds length limit.` and are cleared.
- The custom UI clears the bridge payload before sending a command and after consuming a matching response.
- Regenerated `plugin.py`.

Verification:
- `pytest -q`: 123 passed.
- `python -m py_compile plugin_core.py plugin.py .github/scripts/generate_plugin.py`: passed.
- `git diff --check`: passed.
- `python .github/scripts/validate_plugins.py`: passed for 327 plugins after adding `MarstekCT` to the registry in the same local batch.

Public action:
- Push approved by the maintainer.
- No issue comment or close action has been taken yet.
