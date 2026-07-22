# ISSUE:117 - no option for local registry

Status: open; diagnostic reply posted, awaiting reporter confirmation.

Author:
- `Eddie-BS` opened the issue on 2026-07-22 after upgrading a remote Domoticz
  installation to the latest release.

Intent:
- Create a local registry override for the installed
  `solaredge-modbustcp-plugin` checkout, which is correctly shown as a repository
  mismatch.

Assessment:
- The screenshot reports PyPluginStore `v2.21.0` from the installed plugin files,
  but its header lacks the **Local registry** action and still renders an older
  custom-page layout.
- The tagged `v2.21.0` `pypluginstore.html` contains the global **Local registry**
  action. PyPluginStore copies that page into Domoticz `www/templates` during
  plugin startup, so the installed code can be current while the served page
  remains old until Domoticz reloads the plugin.
- This is most likely a restart/browser-cache or custom-page deployment issue.
  Product-code changes are premature until that path is checked.

Verification:
- The current custom page contains and wires the accessible Local registry
  dialog.
- Local public-package overrides remain supported and explicitly Git-managed.
- Five focused UI, local-registry, and release-action tests passed on 2026-07-22.

Recommended next step:
- Await confirmation after a Domoticz restart and browser hard refresh.
- If it remains absent, request only the relevant log line containing `Custom UI
  autoinstalled/updated`, `Custom UI is already up to date`, or `Custom UI
  autoinstall failed`; then inspect source/destination page freshness and write
  permissions.

Public action:
- Posted the approved diagnostic reply:
  `https://github.com/adrighem/PyPluginStore/issues/117#issuecomment-5042788930`.
