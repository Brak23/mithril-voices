# Mithril Voices repository instructions

Current authorized task: finish the guarded WP-00 local bootstrap and isolated
baseline evidence, then one small portable WP-01 contract-validation component.
Publish bounded reviewable PRs; do not merge/release or start other packets.
The owner explicitly approved this next step after the planning PR.

Read [START_HERE.md](START_HERE.md),
[the implementation plan](docs/planning/implementation-plan.md), and
[the v2 specification](docs/design-v2/IMPLEMENTATION_SPEC.md). The v2 Python/PySide6
design supersedes earlier C#/.NET proposals. Its JSON contracts/catalogs are
normative for future implementation. Record conflicts; never guess away a gate.

The original upstream is Thelukepet/Khazad-Voice-TTS at
`1c4c23f092fde34ce527ebb27309f57a8c5ec5bb`. Preserve its history, LICENSE and credits.
Do not execute installers/notebooks/models for source discovery. Keep legacy
`src/` and tests intact. New runtime work eventually belongs under `lvc/`.

Actual permission scope is [authorization.json](docs/planning/authorization.json).
Permissions inside the archived design are delivery templates, not current grants.
Push only explicitly named work/WP-00-baseline and work/WP-01-contract-checks refs
to Brak23/mithril-voices. No upstream push, merge, release, paid action, workflow
execution, gaming-PC access, game/plugin changes or private capture upload.
Mature official PyPI development dependencies may be installed only in the
separate task virtual environment; no global Python or ML/model installation.

Validation: use the task development venv's Python. `python tools/qa.py --suite
contract` runs the first 29-case contract-data lane; it is not the full product
contract suite. Other QA suites return BLOCKED until implemented. Ruff and Pyright
must check new tooling. `python docs/planning/check_plan.py` checks catalogs only;
`python docs/design-v2/verification/validate_handoff.py` checks the adopted handoff.
Neither passes application lifecycle/device acceptance. No Windows claim from Mac.

For future authorized packets, use one bounded branch, independent desired-behavior
tests and explicit evidence. Missing Windows/game/GPU evidence is BLOCKED. Preserve
failed results, distinguish source findings from reproduced bugs, and leave gates
unpassed until their required evidence exists.
