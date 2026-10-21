# Local panel localization preview

For the later box-free structural trial and its separate qualification limits,
see [windows-structural-auto-trial.md](windows-structural-auto-trial.md). This
document records the earlier manually marked template-preview baseline.

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

## Historical local screenshot check

The repository already contains eleven August 2025 game screenshots under
`experiments/test_screenshots/`. All eleven visibly show an open quest pane in
roughly the same position and UI scale; they provide no closed-pane negatives
or moved-panel examples. A local probe calibrated an 80 x 38 border anchor and
600 x 750 body box on `195436`, then searched the other ten without changing
the similarity threshold. It found 10/11 open panes; `201322` returned
`NOT_FOUND` at similarity 0.860, below the 0.88 threshold. The changed title
art appears to affect this anchor. Lowering the threshold without negatives
would give no evidence about false starts.

The current Windows OCR adapter admitted text from both variants of each of
the ten located body crops. This establishes only that the output was nonempty
and internally consistent. No manual transcription, word accuracy, crop
completeness, or live-game behavior was scored. These related screenshots are
development examples, not an independent held-out set. No screenshot or OCR
content was copied into a new artifact by this check.

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
