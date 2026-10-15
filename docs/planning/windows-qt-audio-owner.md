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
frames with a measured -36.005 dBFS digital peak. The physical run is pending
confirmation that the powered speakers are connected to that Realtek endpoint;
the headset and two Steam virtual outputs are distinct. No endpoint volume or
system setting changed.

The first user-approved run will record the endpoint identity, negotiated
format, actual buffer size, write count and software Stop/reset timing. Actual
drain accounting and physical Stop-to-silence measurement remain separate
qualification work. The test will not open LOTRO.

The production worker launch/manifest adapter and in-progress `.part` size and
deadline limits remain prerequisites before real model output can feed this
owner. LOTRO, capture, model and content rights gates are untested. WP-03,
WP-04 and G1 remain incomplete.
