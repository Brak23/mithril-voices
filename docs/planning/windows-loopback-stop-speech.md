# WP-04 bounded Realtek loopback and speech checks

The Windows audio owner now polls the selected `QAudioSink` for consumed PCM
frames on its Qt thread. It reports completion only after every frame of the
validated unit was accepted and drained and Qt reports an idle sink. A Stop
raises the generation floor before the queued reset; drain callbacks are
ignored after that floor rises. The physical adapter uses a bounded 50 ms
prefill and still caps accepted, undrained PCM at 500 ms. No endpoint fallback,
master volume change, or background recorder is added.

The exact selected endpoint was `Speakers (Realtek(R) Audio)` with ID
`{0.0.0.00000000}.{a1d419f2-e6af-4a0e-8c3e-e5395c018f6d}`. SoundCard
0.4.6 opened its stereo WASAPI output loopback for this endpoint; the
microphone was not opened. Its official wheel was inspected and installed
only into the repository task venv. Captures were bounded to one attempt each
and retained only derived measurements. Local receipts outside Git are
`../wp04-loopback-stop.json` and `../wp04-loopback-speech.json`. Attempt
markers prevent unintentional duplicate playback.

The Stop test used an original 440 Hz, 500 ms source at approximately
-36 dBFS. Stop was requested 120 ms after the first accepted write. The
renderer accepted 6,240 of 24,000 source frames, reset 2.17 ms after the
Stop request, rejected an old-generation submission, and did not complete
the old unit. The output loopback detected seven active 10 ms blocks and
37 quiet blocks after the last detected tone. The last active block was
returned 4.29 ms after the Stop request. This timestamp has at least 10 ms
block uncertainty and unmeasured WASAPI buffering. One trial is not a
latency distribution or an acoustic silence claim.

The generic speech test used the original short text, “The road is clear,”
synthesized locally with the installed Windows System.Speech voice. It was
converted to validated 48 kHz mono Int16 PCM, attenuated with a 20 ms fade
and a measured -36.005 dBFS peak, then passed through the same owned WAV
spool validation, generation fence, exact-device sink and drain completion.
The source was 89,496 frames (1.865 s); the sink accepted all 178,992 bytes,
reported one renderer completion, no loss or rejection, and no errors.
Stereo output loopback measured 91 active 10 ms blocks and 101 quiet blocks
after activity. The private generated WAV stays under task temporary storage
and is not part of this branch. This tests generic local speech transport,
not the project's proposed TTS model or its rights.

The fake sink drain check, Ruff, Pyright and Windows `qt-audio-owner` lane
passed (21 collected, none failed or skipped) after the drain change.
The physical checks were single bounded trials before the final floor guard
was added; the guard was subsequently covered by the fake/owner checks.
Actual in-game Stop timing, selected-window capture/OCR, model quality,
repeat-run latency and acoustic output remain unqualified. WP-04 and G1
remain incomplete. LOTRO is not needed for further WP-05 capture-adapter
construction; a deliberate game run will be useful after the selected-window
identity and privacy probe is ready.
