# ISSUE:117 - no option for local registry

Status: closed; restart and browser refresh resolved the stale custom page.

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
- The reporter confirmed after restarting and refreshing that the Local registry
  action appeared, then closed the issue:
  `https://github.com/adrighem/PyPluginStore/issues/117#issuecomment-5042855586`.

Recommended next step:
- None. Reopen only if a future restart still fails to deploy the current custom
  page, with the narrow custom-UI autoinstall log line.

Public action:
- Posted the approved diagnostic reply:
  `https://github.com/adrighem/PyPluginStore/issues/117#issuecomment-5042788930`.
