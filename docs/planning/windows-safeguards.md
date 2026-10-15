# Windows cancellation and audio admission slice

This local branch stacks on PR #6. `lvc/safeguards.py` adds deterministic host
primitives that a later QProcess supervisor and single Qt audio owner can use.
It is a bounded slice of R-CTL-004, R-IPC-002/004/005 and R-AUD-OUT-001/002.

The worker ledger records one effective host terminal outcome. Stop can mark a
request canceled immediately while the worker is still physically occupied.
`cancel_ack` records receipt only. A 250 ms missing-ack diagnostic and 1,000 ms
process-tree termination instruction use monotonic fake time. The slot is
reclaimed only after a worker terminal or observed tree exit. Duplicate and
late terminals cannot resurrect canceled A. At most 256 active/recent records
are retained; reclaimed records are pruned on pressure.

The audio gate checks host session, generation, intent, page, prepared request,
fence acknowledgment, sink epoch, unit order and cancellation immediately
before each fake sink write. A new generation waits for fence acknowledgment.
Stale sink callbacks cannot complete a new unit; idle before all frames are
submitted and drained is an underrun, not completion. Cache-sourced clips use
the same host authorization gate. All tests use original synthetic content.

`python tools/qa.py --suite safeguards` runs eleven deterministic tests. Two
tests inject deliberately wrong behavior in memory: bypassing the final host
generation check and treating `cancel_ack` as physical reclamation. Their
independent assertions fail under those mutations. This is not the complete
five-mutant AT-070 campaign or the 1,000/10,000 schedule replay.

These primitives have no QAudioSink, OS process-tree adapter, IPC parser,
artifact decoder, or real device. The fake sink only records calls. Therefore
AT-001/004/005/047 are **partial synthetic evidence**, and physical Stop
latency, process containment, capture, game, model and GPU qualification are
**not run**. WP-01 through WP-04 and G1 remain incomplete. The branch stays
local pending read-only clarification of the fork's metered GitHub AI Scan
setting; no new remote push or PR was made for this slice.
