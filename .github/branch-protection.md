# Master Protection Design

## Goal

Protect `master` without breaking the trusted workflow that regenerates
`plugin.py` after a push.

## Implemented CI prerequisites

- Workflow defaults are read-only.
- Pull requests regenerate `plugin.py` with read-only permissions and fail when
  the committed file is stale.
- Only the trusted `master` push generation job receives `contents: write`.
- Checkout credentials are not persisted in pull-request validation jobs.
- Every action is pinned to a full immutable commit SHA.
- Repository regression tests enforce these invariants.

## Repository settings

Applied on 2026-07-18:

- Default `GITHUB_TOKEN` permissions are read-only.
- Workflow approval of pull-request reviews is disabled.

After the workflow changes reach `master`, require full-length action SHA pinning.
Enabling that setting earlier would reject the current tag-based workflow files on
the remote default branch.

## Proposed ruleset

Create a repository ruleset targeting the default branch in `evaluate` mode
first:

- Block force pushes.
- Restrict branch deletion.
- Require pull requests for human changes.
- Require `validate (ubuntu-latest)`, `validate (windows-latest)`, and CodeQL.
- Require conversations to be resolved.
- Do not require the path-filtered plugin-generation check globally; the validate
  suite already includes generated-file parity and the check is absent from
  unrelated pull requests.

The current generation workflow pushes a follow-up commit directly to `master`.
A pull-request requirement therefore needs one of these designs before active
enforcement:

1. Preferred: change generation to open/update a narrowly scoped generated-file
   pull request. No branch bypass is then required.
2. Transitional: grant bypass to a dedicated GitHub App used only by the
   generation workflow. Do not grant a blanket GitHub Actions bypass, because it
   would let every write-capable workflow bypass the ruleset.

Keep the ruleset in evaluation until a real release and registry update exercise
the selected path. Then review rule insights and activate it.
