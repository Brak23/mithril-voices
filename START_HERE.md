# Mithril Voices planning handoff

Start with [the concrete implementation plan](docs/planning/implementation-plan.md).
The complete text/JSON requirements are retained under [docs/design-v2](docs/design-v2/).
The original ZIP remains outside this repository. Personal references were removed
from the published text; no chat transcript or DOCX metadata is included.

This PR completes requirements adoption and planning only. It does not complete
WP-00/G0: a tested guarded bootstrap, preserved baseline worktree, full baseline
test classification and rights inventory still need their own scoped work.
All 85 application acceptance cases remain NOT_RUN.

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

The next proposed task is a bounded completion of WP-00. Do not repeat fork
creation, clone over the current checkout, reset user work, install dependencies,
change the default branch or continue into broad implementation automatically.
