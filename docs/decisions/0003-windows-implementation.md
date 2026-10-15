# ADR 0003: Windows implementation scope

Status: owner authorization recorded, 15 October 2026.

After the first three stacked draft PRs, the owner granted access to the Windows
PC and requested implementation of the pieces that can proceed now. The owner
will run LOTRO when that step is ready. Work can continue through bounded,
dependency-ready code and test packets with reviewable branches and PRs. The
game is not launched or modified by this authorization.

The earlier planning and Mac-only scope statements remain historical records;
this owner instruction supersedes their narrower implementation limit. It does
not change the v2.0 product behavior, acceptance thresholds or evidence gates.
No merge, release, paid service, unapproved model/asset download, game/plugin
change, private capture upload or workflow execution is authorized. Official
PyPI development dependencies may be installed in the isolated task venv.

Windows baseline work starts from PR #3's `e4f7929` ancestry, not upstream main.
The immutable upstream baseline remains `1c4c23f092fde34ce527ebb27309f57a8c5ec5bb`.
Mac reports remain Mac evidence. Windows tests and blockers are recorded
separately under `docs/evidence/wp00/`.

Affected authority IDs: R-GOV-001/002/003/004, R-REP-003, R-TST-004.
No acceptance test or release gate is waived.
