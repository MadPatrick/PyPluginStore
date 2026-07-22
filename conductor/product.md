# PyPluginStore Product Context

PyPluginStore is a Domoticz Python plugin manager. It provides a custom Domoticz UI for discovering, installing, updating, and removing third-party Domoticz Python plugins from a curated registry.

The registry is distributed as JSON and refreshed by scheduled GitHub Actions scans. The runtime plugin must work on Linux/Raspberry Pi and Windows Domoticz installations with Python plugin support.

Current priority: make checksum-pinned release archives the preferred install and
update path. Git remains supported for packages without certified releases,
Local registry overrides, and verified rollback recovery; intentional ongoing
Git management uses a Local override instead of a public Release-to-Git switch.
Release resolution must work consistently for GitHub, GitLab,
Codeberg/Forgejo, Gitea, and generic HTTPS manifests without exposing
forge-specific behavior to users.
