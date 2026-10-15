# Mithril Voices planning handoff

Start with [the concrete implementation plan](docs/planning/implementation-plan.md).
The complete text/JSON requirements are retained under [docs/design-v2](docs/design-v2/).
The original ZIP remains outside this repository. Personal references were removed
from the published text; no chat transcript or DOCX metadata is included.

The planning PR completed requirements adoption only. Subsequent stacked PRs
added guarded bootstrap and the first contract-data slice. On Windows, see
[the baseline report](docs/evidence/wp00/windows-baseline.json) and
[ADR 0003](docs/decisions/0003-windows-implementation.md) for the current scope.
The [WP-01 foundation report](docs/evidence/wp01/windows-foundation-summary.json)
records the next bounded development slice. These results do not complete
WP-01/G1 or game, model, audio and capture gates.
The [WP-02 Stop core note](docs/planning/windows-core-stop.md) and
[synthetic Windows report](docs/evidence/wp02/windows-core-stop.json) cover a
pure reducer slice only; WP-02 remains incomplete.
The [Windows safeguards note](docs/planning/windows-safeguards.md) records the
next local synthetic cancellation and audio-admission slice. It does not
qualify actual QAudioSink or worker process containment.
The [Windows Job Object probe](docs/planning/windows-job-probe.md) is the next
local WP-03 experiment with controlled test processes; it does not qualify the
production worker launcher or real LOTRO.
The [synthetic single-unit flow](docs/planning/synthetic-flow-integration.md)
connects the reducer, supervised fake worker, and fake playback controller;
artifact and physical audio qualification remain open.
The [generated WAV spool slice](docs/planning/windows-spool-validation.md)
checks actual synthetic file bytes and ownership before fake sink admission.
The [synthetic Qt audio owner slice](docs/planning/windows-qt-audio-owner.md)
pumps verified PCM on one Qt thread with generation fences and a fake backend;
physical playback remains disabled.

Read these in order:

1. [Repository adoption decision](docs/decisions/0001-planning-adoption.md)
2. [Source audit](docs/planning/source-audit.md) and [reuse map](docs/reuse-map.md)
3. [Implementation specification](docs/design-v2/IMPLEMENTATION_SPEC.md)
4. [Contracts README](docs/design-v2/contracts/README.md), defaults, wire schema,
   behavior matrix, requirement index, acceptance catalog and tasks
5. [Uncertainties and blockers](docs/planning/implementation-plan.md#uncertainties-and-blockers)

Run `python3 docs/planning/check_plan.py` for the repository's planning consistency
checks. This is not application QA. The original package validator is preserved
for inspection under `docs/design-v2/verification/`; its schema rerun is blocked
on this environment's missing `jsonschema` dependency.

The earlier adoption prompt predates the current Windows authorization. Use the
current [authorization record](docs/planning/authorization.json) and packet graph
for subsequent work. Preserve user work, fork history and the existing baseline;
do not repeat fork creation or change the default branch automatically.
