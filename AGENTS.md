# Mithril Voices repository instructions

Current authorized task: adopt and review the v2 requirements, audit source, and
deliver a documentation-only implementation plan and PR. Do not start application
implementation from the broad adoption prompt without a new scoped task.

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
Push only an explicitly named planning ref to Brak23/mithril-voices. No upstream
push, merge, release, paid action, workflow execution, game/plugin changes,
private capture upload or dependency/model installation is authorized by this task.

Validation: `python3 docs/planning/check_plan.py` checks planning data only.
The separately reviewed source validator needs `jsonschema`; do not install it
implicitly. `tools/qa.py` does not exist yet and is a future WP-01 deliverable.
Do not claim its suites or any application acceptance cases passed.

For future authorized packets, use one bounded branch, independent desired-behavior
tests and explicit evidence. Missing Windows/game/GPU evidence is BLOCKED. Preserve
failed results, distinguish source findings from reproduced bugs, and leave gates
unpassed until their required evidence exists.
