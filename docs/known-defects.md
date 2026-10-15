# Known source findings and reproduction status

See [source-audit.md](planning/source-audit.md) for path/function evidence and
[implementation-plan.md](planning/implementation-plan.md#defect-corrections-and-independent-acceptance-oracles)
for fixes and AT mappings. These are SOURCE_OBSERVED, not reproduced game failures.

BUG-01 through BUG-08 in v2 are confirmed source patterns: blocking retail callback,
shared cancellation/unbounded work, missing terminal on producer exception, watcher
busy-spin/truncation gaps, destructive OCR, permissive corpus matching, shallow
streaming test and license/dependency inconsistency. Runtime incidence is UNVERIFIED.

Additional source observations: backend-specific memory load is paired with a save
call that omits backend; reference voice IDs depend on enumeration; the installer
downloads upstream main and uv latest; ConfigManager/utils perform filesystem
operations during initialization/import. None has been patched in this PR.

The baseline suite has 82 static test function definitions across five test files.
This is an AST inventory, not pytest collection, coverage or a passing test count.
Tests have not been imported or executed. Their runtime outcomes and environment
classification remain NOT_RUN until the isolated WP-00 baseline task.
