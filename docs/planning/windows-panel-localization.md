# Local panel localization preview

## What the prototype does

`PanelLocator` takes an in-memory selected-window frame and returns a reason,
visual similarity, and candidate anchor, approximate panel extent, and body
boxes. `TemplatePanelLocator` learns one distinctive anchor from the existing
user-marked open-pane calibration, searches at 0.85/1.0/1.15 scale, rejects
ambiguous or missing matches, and maps the body relative to the found anchor.
It searches near the prior box first, then falls back to a full-frame search.
It uses local CPU OpenCV only. The UI has a **Preview moved panel (speech off)**
button; its candidate boxes are transient and cannot arm narration. The
installed automatic reader continues using the saved fixed regions until
held-out real-game localization and text completeness have been assessed.

This baseline still needs one manually marked anchor and body. It removes
neither that first-session calibration nor the need for real-game validation.
The orange preview box is the envelope of the known anchor and body, not a
learned or verified panel boundary. Resize or DPI changes suspend the current
capture binding; reselect and recalibrate before speech. The pure detector
handles synthetic scale changes, but the UI does not silently carry a speech
profile across game geometry changes.

## Measured local synthetic timing

Run `python -m tools.benchmark_panel_locator`. On this Windows machine, five
generated-pattern samples per size gave:

| Frame | Full search median/max | Nearby tracking median/max |
| --- | ---: | ---: |
| 800 x 500 | 13.1 / 14.2 ms | 2.2 / 2.6 ms |
| 2560 x 1440 | 119.5 / 120.4 ms | 5.6 / 6.2 ms |
| 5120 x 1440 | 236.9 / 242.3 ms | 9.1 / 9.6 ms |

These times are CPU measurements on simple generated art. They do not measure
real LOTRO detection accuracy, game impact, graphics contention, or speech
latency. If later qualified for continuous use, discovery should be periodic,
tracking should use a bounded latest-frame queue, and inference must yield to
the game. Do not run a large model on every 500 ms capture by default.

## Evidence needed before autonomous localization

Collect local, owner-approved frames of a stock quest pane at moved positions,
UI scales, resolutions and ultrawide layouts; label complete panel and body
boxes. Include close/reopen, partial occlusion and distinct journal, map,
vendor, chat, inventory and loading sequences. Report box localization,
**complete and uncontaminated body crops**, false audible starts per exposure,
and crop-to-first-audible/Stop timing separately. Split by source, UI setup and
gameplay session so nearby frames from the same source do not leak into the
held-out set. The current generated tests prove only coordinate mapping and
conservative abstention on their own fixtures. The v2 G3 held-out qualification
remains open.

Historical online screenshots require a source and license record and an
approved use scope before dataset inclusion. Do not assume publicly visible
images can be redistributed, uploaded, or used to train a distributed model.
Older UI layouts may not predict current-client performance. No online corpus
was scraped or uploaded for this prototype. If a rights-cleared, diverse set
supports a learned detector later, export a pinned local model with a bounded
CPU inference path and feed its boxes through the same `PanelLocator` contract.
It must retain the selected-window, confidence/ambiguity, stable-frame,
text-validation, generation-fencing and fail-silent gates; model output alone
never triggers speech.
