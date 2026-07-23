# ISSUE:122 - Update notification keeps coming when latest Git version is installed

Status: open; clarity fix implemented locally.

Reporter:
- `MadPatrick` reported on 2026-07-23 that seven current Git-managed plugins
  repeatedly produced generic update notifications.

Intent:
- Clearly distinguish a newer plugin version from the option to use the Release
  channel instead of Git commits.

Assessment:
- All seven plugins have indexed releases, but their configured Git branches are
  11–40 commits ahead of those releases.
- Release-first status classifies an existing Git checkout as
  `migration_available`. The notification path treated that state exactly like
  `available`, producing the misleading **Updates Available** subject.
- The custom UI already keeps the checkout on Git and requires confirmation when
  the selected release does not contain the installed Git commit.
- `ISSUE:73` had a similar symptom but a different cause: Git branch status and
  update behavior. This issue is specifically about Release-channel wording.

Resolution:
- Keep normal update notifications for newer plugin versions.
- Use a distinct Release-channel notification for Git-to-Release choices.
- Replace user-facing migration wording with **Use Release channel instead of
  Git commits** in the card status, action, confirmation, README, and release
  management guide.
- Keep internal migration states and all downgrade, ancestry, local-data, and
  confirmation safeguards unchanged.

Verification:
- Focused Release, notification, migration, and UI suite: 192 tests passed.
- Full sanitized suite: 1,360 tests passed.
- Live registry validation: all 257 repositories passed.
- Generated `plugin.py` parity and `git diff --check` passed.

Recommended next step:
- Ship the clarity fix and ask the reporter to confirm that future notifications
  clearly identify the Release-channel choice.

Public action:
- Posted the approved explanation:
  `https://github.com/adrighem/PyPluginStore/issues/122#issuecomment-5059478892`.
