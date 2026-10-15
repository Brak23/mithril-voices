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

A subsequent local `QAudioSink` backend now requires an exact device ID,
validates the 48 kHz mono Int16 format, and requests a 50 ms sink buffer. It
can be enabled only by an explicit service opt-in; the physical probe requires
an additional `--play` argument. The no-playback preflight found the Windows
default Realtek speaker endpoint, verified the format, and submitted zero
frames. A separate generated 0.25-second, 440 Hz tone contains exactly 12,000
frames with a measured -36.005 dBFS digital peak. Bryce confirmed the Realtek
speakers, and one guarded physical attempt was made. That attempt submitted
zero bytes: our code compared the `QtAudio.Error` returned by `QAudioSink`
against the different `QAudio.Error` enum, causing a valid `NoError` value to
be mistaken for failure. The resulting `DEVICE_LOST` receipt is the owner's
generic failure label, not evidence that the Windows endpoint disconnected.
The failed receipt was preserved outside the repository. No endpoint volume
or system setting changed.

The enum comparison is corrected. Silent starts on the Realtek endpoint now
return an open `QIODevice` and `NoError` in the main thread, owner thread,
owner thread after reset, and exact backend object. All four diagnostics wrote
zero PCM bytes. A fake-sink test exercises the corrected backend write path
without opening a physical device. A second audible attempt is not included in
this batch. It still needs its own authorization; actual drain accounting and
physical Stop-to-silence measurement remain separate qualification work.

The production worker launch/manifest adapter and in-progress `.part` size and
deadline limits remain prerequisites before real model output can feed this
owner. LOTRO, capture, model and content rights gates are untested. WP-03,
WP-04 and G1 remain incomplete.
