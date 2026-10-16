# Resident Kokoro worker candidate (WP-03/06 slice)

`lvc/tts/resident_kokoro_worker.py` loads the already approved pinned Kokoro
CPU model once and emits complete validated private WAV units. It renders one
phrase, then waits for an exact `next` acknowledgment before rendering another.
Changing voice requires replacing the worker. There is no device access, model
download, network call, live capture, or audio playback in this packet.

The bounded Windows probe launches the worker in an owned Job Object, verifies
the nonce and selected voice, checks each WAV path/hash/format, submits a second
request to the same loaded process, and removes its private spool on exit. It
does not claim full IPC contract conformance or production process supervision.
The host's final generation fence and Qt audio owner still govern whether a
unit may become audible. A Stop must terminate a busy worker asynchronously;
the worker cannot interrupt a native inference call merely by receiving text.

## Windows evidence

- Full `tests/v2` suite with workspace `--basetemp`: 227 passed.
- Ruff and Pyright on the new worker, probe and tests: passed.
- `python -m tools.windows_resident_kokoro_probe`: passed. One silent run:
  model ready at 9,415 ms after process launch, first complete unit at 10,120
  ms, and a subsequent warm request's complete unit at 534 ms. The two first
  request units were 103,200 and 97,200 frames at 48 kHz. These are one-run
  software timings, not audible onset or a latency percentile.

Integration with the automatic detector, cancellation, cache, Qt sink, physical
speaker, and paused playback is still open. This packet does not pass G2/G3 or
enable unattended narration.
