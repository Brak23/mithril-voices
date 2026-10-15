# First portable component: strict contract-data validation

This is the bounded WP-01 slice authorized after the planning PR. It does not
implement the narrator or complete WP-01/G1. The baseline's local adoption/source
audit is available; its full runtime qualification remains blocked as recorded in
[WP-00 evidence](../evidence/WP-00.json).

`tools/validate_contracts.py` loads bounded UTF-8 JSON objects, rejects duplicate
keys, nonfinite values and malformed/oversized documents, and validates the exact
shipped defaults and IPC syntax against reviewed bundled Draft 2020-12 schemas.
It never executes payload text, imports a model, starts workers or authorizes audio.
Valid syntax alone does not establish role, current generation, nonce, permissions,
real file containment or actual PCM integrity. Those remain future host duties.

The 23 original contract cases cover safe defaults, unsafe/unknown/missing fields,
Unicode length boundaries, strict wire versions/types/booleans, traversal-shaped
descriptors, immutable input handling, duplicate keys, NaN/Infinity, invalid UTF-8,
oversized objects and missing files. The suite initially failed collection because
the implementation module did not exist; the red output is preserved. Six QA-lane
cases additionally prove zero tests, subprocess errors, failures and unexpected
skips cannot pass, and Windows stays BLOCKED.

Run using the isolated development environment:

```text
python tools/qa.py --suite contract --report docs/evidence/WP-01-contract.json
ruff check tools/bootstrap_repository.py tools/validate_contracts.py tools/qa.py tools/test_bootstrap_repository.py tests/v2
pyright --pythonpath <DEV_PYTHON> tools/bootstrap_repository.py tools/validate_contracts.py tools/qa.py
```

Actual results: 29 contract/QA tests passed, zero failures/skips; 11 bootstrap
tests passed separately. Ruff passes and Pyright reports zero errors/warnings
when pointed at the selected venv. The reviewed original package validator now
passes 625 checks; the adopted text package passes its own checksum/schema check.
Neither is a runtime application test. Exact development package versions are in
`docs/evidence/wp00/mithril-dev-freeze.txt`; this is an observed Mac environment
snapshot, not a hash-locked Windows runtime manifest.

`quick`, `replay`, `windows`, `gpu`, `package` and `release` explicitly return exit 2
and BLOCKED. The current contract lane has a fixed test inventory, a 60-second
subprocess timeout, no external pytest plugin autoload, real JUnit counts and an
evidence report with code SHA, dirty flag, spec/input hashes and environment.
The full contract suite will also need lifecycle/process/sink cases; those are not
substituted with this smaller data-validation lane.

Baseline notes: the preserved worktree is detached at the full audited SHA; no
experiments execute there. All 255 tracked files match its disposable probe copy.
46 legacy tests pass. Three modules fail collection due missing nltk/cv2, blocking
36 definitions; those are environment gaps, not reproduced app defects. The 29
manual tracking tests mirror helpers and are not evidence of real ingestion.
The baseline harness denial of network/process launch is a test guard, not a
security sandbox; only reviewed source/tests were executed. To reproduce, copy
the stored harness to the task folder beside `baseline-probe`, prepare a disposable
copy of the pinned worktree, then use its recorded commands and isolated state dir.

The first component stops here. Remaining work includes complete WP-01 locks/QA
inventories/fake process and sink infrastructure, Windows Python 3.12 qualification,
then a separately scoped WP-02 coordinator. No merge, release, gaming-PC access,
workflow execution, paid service or broad application implementation occurred.
