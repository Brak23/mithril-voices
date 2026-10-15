# WP-03 single-unit synthetic flow

The shortest local path to a text-to-playback-controller proof reuses the v2
schema validator, pure reducer, worker cancellation ledger, final audio gate,
and the controlled Windows QProcess fixture. `lvc.synthetic_flow.SyntheticFlow`
connects these existing boundaries. It accepts caller-validated synthetic text,
submits one immutable request, checks a supervised terminal envelope and exact
context, calls an injected artifact verifier, stages one unit, and admits fake
sink writes only after a matching fence acknowledgment. A unit reaches
`COMPLETED` only after all source frames are written and the fake ring is
drained. A worker error or invalid artifact fences the unit and enters `FAILED`.

The QProcess fixture now has a `success` case: its contained original worker
returns a schema-valid synthetic audio descriptor. The flow injects a fake
verifier and a recording sink. Its `submit` port sends the flow's actual text
and immutable context over the QProcess channel. **No WAV file is created or accepted by a real
verifier, and no physical audio is opened.** This case proves message-to-control
wiring; it does not prove the descriptor or clip safe for playback. The
[Windows report](../evidence/wp03/windows-synthetic-flow.json) records the
seven pure flow cases plus eight controlled QProcess cases. Tests include Stop
before completion, failure, rejected audio, mismatched context, duplicate
terminal, partial-write Stop, and a retired worker's queued result after B
starts. The worker slot remains occupied until tree exit; B uses a new worker
instance ID. A missing audio fence acknowledgment stages the unit without a
write.
The [individual QProcess success result](../evidence/wp03/windows-synthetic-success.json)
records one fake sink write and owned descendant cleanup.

## Gate reconciliation and next production dependency

| Packet | Current evidence | Still required |
| --- | --- | --- |
| WP-01 | Pinned contracts, guarded bootstrap, original fixtures, bounded QA | Full independent reference schedules, remaining Windows lock and test infrastructure qualification |
| WP-02 | Pure Stop subset, cancellation ledger, single-unit playback transitions | Complete behavior-matrix transition table, scheduling/queue rules, property and mutation schedules |
| WP-03 | Strict schema data checks, controlled Job Object/QProcess probes, this synthetic flow | Reusable production QProcess adapter with a safe launch barrier, actual artifact manifest and PCM spool verification, deadlines/breaker, all required protocol cases |
| WP-04 | Final-write and drain logic with a fake sink | One QAudioSink owner, device selection, physical reset/fence acknowledgment, endpoint Stop measurements and recovery |

The next dependency-ready implementation is host-owned spool validation of a
complete synthetic WAV unit, followed by a reusable supervisor-to-controller
adapter with real manifest identity. That work can use original synthetic
files and needs no LOTRO, model, or audio endpoint. G1 and AUDIO_SLICE are not
passed. No LOTRO launch, model download, game-file change, physical audio,
capture, or external service was used here.

The later [generated WAV spool validation](windows-spool-validation.md)
replaces the fake verifier in the controlled QProcess success case. This page's
15-case report remains evidence for its original commit.
