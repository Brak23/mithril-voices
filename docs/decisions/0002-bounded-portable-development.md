# ADR 0002: approved baseline work and first portable component

Status: recorded owner scope amendment. The owner approved baseline setup/tests
followed by the first small dependency-ready component. No merge, release, paid
service, game changes or gaming-PC access is authorized. The earlier planning-only
restriction is superseded only for this bounded work.

WP-00 uses the existing clone rather than implementing remote creation. Its guarded
script defaults to dry-run, refuses identity/path/tag/dirty conflicts before writes,
checks every Git result, disables repository hooks, configures upstream push denial
and creates/verifies a pinned detached baseline. Tests live alongside this setup
tool; their inclusion is necessary to the explicitly authorized bootstrap task.

Local setup/source inventories and baseline classification are available. In an
isolated disposable copy, 46 legacy tests pass; 36 definitions remain blocked by
minimal environment dependencies. The Mac's Python 3.14 is a portable probe only,
not the contract's Windows Python 3.12 runtime. No ML environment is installed to
erase that limitation. Rights inventories preserve unknown redistribution status.

The first dependency-ready WP-01 slice is developer contract-validation tooling
with focused independent negative tests. It does not start a narrator, coordinator,
capture/voice adapter, Qt UI or later packet. The full WP-01 and G1 are not complete
until their remaining test infrastructure and Windows lock obligations are met.
Windows/device/GPU gates remain blocked; this does not block portable data checks.

Use stacked PRs: WP-00 against the unmerged planning branch, then WP-01 against
WP-00. Each remains independently reviewable. Do not change the default branch or
merge either. Every published commit uses [skip ci] to retain the no-workflows scope.

The archived design catalogs remain an unmodified requirements snapshot. Current
progress/authorization reports are overlays; the authoring validator's expectation
of NOT_STARTED/NOT_RUN templates is not authority to erase actual execution data.

Affected IDs: R-GOV-001/004, R-REP-001/003, R-AUD-001, R-SCP-004, R-TST-004.
Product behavior and thresholds remain v2.0; no release evidence is waived.
