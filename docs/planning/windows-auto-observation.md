# Windows automatic observation candidate (WP-08 slice)

This branch adds the pure observation policy in
`lvc/vision/auto_observation.py`. It does not enable automatic capture or
speech. The existing manual Desktop launcher remains the known working path.

The policy accepts only observations from one explicitly bound window and one
geometry epoch. Its caller must first verify the native LOTRO process/window
identity and apply a qualified detector profile. It waits 300 ms for stable
content, returns one validation token, fences on a credible change, requires two
valid absence checks at least 125 ms apart for panel closure, and deduplicates a
validated page within an interaction. Stop revokes pending validation and holds
the same page; Stop before page identity is known requires rearming or a
confirmed close/reopen. A geometry or profile failure suspends Auto; rebinding
never rearms it. The module does not save pixels or text.

The test image is generated locally at test time. It exercises the installed
Tesseract binary with two passes and verifies that `Bring 10 Ore. Do not trade
1.` remains unchanged. This proves the test path on synthetic text only. The
input `qualified=True` in the tests stands for detector evidence that does not
yet exist for retail LOTRO.

## Current gate ledger

| Area | Status | Next evidence |
| --- | --- | --- |
| Stable page/change/close/Stop policy | Passed on synthetic observations | Integrate with bounded worker and actual callback |
| Two-pass OCR preservation | Passed on one generated Windows image | Frozen LOTRO crop profile and held-out cases |
| Retail quest-panel detector | Blocked; no qualified profile | Owner-run LOTRO capture with stock UI, scale and negative surfaces |
| Resident Kokoro and phrase admission | Lab prototype only | Supervised worker, final audio fence and endpoint measurements |
| Auto UI, Pause, speaker and calibration persistence | Not implemented in this packet | Implement against actual qualified detector/renderer |
| Production G3 | Not passed | 500 positive, 500 negative, 100 sequence evaluation plus game-impact and session gates |

No real LOTRO window was captured, no audio device opened, and no game or display
setting changed during this packet. Real-game Auto must remain disabled until
the detector, OCR, lifecycle, audio, and owner qualification gates pass.
