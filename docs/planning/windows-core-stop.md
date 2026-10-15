# Windows WP-02 Stop core slice

This branch adds a stdlib-only pure reducer in `lvc/core.py` for seven typed
events: Auto enable/disable, Stop, Read Current, confirmed page, validated
text, and synthesis completion. It is a bounded implementation slice of
R-CTL-001 through R-CTL-004. The reducer returns immutable state and ordered
host effects. `fence` precedes cancellation, and a worker result is accepted
only for the current session, intent, generation, request and page. A completed
worker produces `prepare_audio`, never permission for a sink write.

Page identity contains interaction UUID, revision, surface and content digest;
the upstream observer must qualify those fields. A known-page Stop records a
page-specific tombstone. A Stop before identity is known records
`AUTO_HELD_UNKNOWN`, which time and OCR alone cannot clear. A manual Read or
an explicit Auto off/on cycle can rearm the latter. Distinct confirmed content
fences the prior page before capture. Duplicate confirmed pages do nothing.

`python tools/qa.py --suite core-stop` runs seven deterministic synthetic
tests. Windows evidence is in `docs/evidence/wp02/windows-core-stop.json` and
its JUnit companion. The evidence records a dirty-tree development run; a
clean committed-SHA run is performed separately after commit. These tests
exercise reducer decisions only and do not satisfy full AT-001, AT-002 or
AT-010 across the child IPC and renderer.

The exhaustive 31-event transition table, final audio-write admission,
sink-instance fencing/acknowledgment, process-tree cancellation and bounded
scheduler are pending. So are real capture, LOTRO, audio endpoint and model
qualification. WP-01, WP-02 and G1 are still incomplete. No game or model
assets were run or obtained for this slice.
