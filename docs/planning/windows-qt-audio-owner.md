# WP-04 synthetic Qt audio owner slice

This local branch adds a single `QThread` owner with a 10 ms `QTimer` pump.
It accepts an `AcceptedUnit` and checks its PCM length and the supplied reducer
and worker ledger authorization; the caller remains responsible for obtaining
that unit from the Windows owned-handle WAV validator. The owner holds
one unit, writes at most 480 frames per pump, and caps accepted frames awaiting
drain at 24,000 (500 ms). Backend partial writes advance the counters by only
the accepted frames. An idle callback before complete write and drain reports
an underrun, not unit completion.

`QtAudioService.fence()` raises a synchronous generation floor before its
queued owner command. The owner resets its injected backend, clears the unit,
increments the sink epoch, and then acknowledges the fence. The floor is
checked again immediately before every backend write. An old idle callback,
old submission, failed backend write, or lost device cannot complete the unit.
Device loss fences the owner and does not select another endpoint. The fake
backend is constructed and accessed on the owner thread with an explicit
synthetic endpoint ID. The service has no `QAudioSink` or device creation path.

The [bounded QA report](../evidence/wp04/windows-qt-audio-owner.json) exercises
normal completion, partial writes, early idle, Stop, device loss, admission
without fence acknowledgment, and a negative write result. The probe uses an
original generated 48 kHz mono PCM WAV, verifies its bytes with the real spool
validator, then passes the in-memory PCM to the Qt owner. No physical playback
was attempted. These cases establish the fake backend's call ordering and
generation behavior only. A queued Stop cannot prove physical silence or a
latency bound; those require endpoint measurement.

The next physical audio batch needs a `QAudioSink` backend owned by this thread,
an explicit selected device, format negotiation with no default-speaker
fallback, an approximately 50 ms requested sink buffer, actual drain accounting,
and measured reset/Stop latency on the selected endpoint. A proposed first
user-approved test is one 0.25-second generated 440 Hz tone at at most -36 dBFS
through the selected endpoint, with an immediate Stop control available.
Before that test, confirm the intended output device and comfortable Windows
volume. Record the endpoint identity, negotiated format, actual buffer size,
write/drain counts, and Stop-to-silence observation. Do not open LOTRO for this
test. The current batch neither enables nor requests that playback.

The production worker launch/manifest adapter and in-progress `.part` size and
deadline limits remain prerequisites before real model output can feed this
owner. LOTRO, capture, model and content rights gates are untested. WP-03,
WP-04 and G1 remain incomplete.
