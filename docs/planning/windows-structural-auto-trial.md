# Windows quest-panel localization trial (WP-09)

## Scope and behavior

The experimental **Find quest pane automatically (trial)** control proposes a
quest panel and the left narrative column from an explicitly captured, selected
retail LOTRO window. It uses native physical pixels, independent vertical and
horizontal line evidence, a second-column relationship, and a local Tesseract
word-layout check. It does not require a user-drawn box, a saved location,
fixed color, fixed font size, or a whole-frame resize. Short/borderless and
unsupported layouts abstain. The manual boxes and manual reader remain.

The selected crop is shown locally for review. The automatic path is session
only: a quest-closed capture and a distinct journal/inventory capture must both
return `NOT_FOUND` before explicit Start. `AMBIGUOUS` fails a control. While
armed, each frame must yield one structural candidate. A missing or ambiguous
candidate fences speech. The body crop is checked again with bounded,
cancelable Tesseract word geometry before the existing dual Windows OCR and
text gates. The existing 300 ms stable-content observation, binding, page
generation tokens, foreground capture restriction, Stop, and voice fences
remain in force. The body digest includes current coordinates so moving or
resizing a pane invalidates an older speech token even if its words match.
No screenshots, recognized words, or model weights are saved by this path.

`QuestPanelDetector.detect(frame) -> PanelDetection` is the comparison
interface for a future trained model. A model would still return candidate
boxes and pass the same negative controls, readable-body, OCR, stability,
binding, and cancellation gates. No model was trained: the available examples
are too few, mostly related, and public-image training rights are unverified.

## Offline replay

`python -m tools.replay_panel_detector MANIFEST [--ocr-layout]` accepts local
images and per-source group/split/label metadata. Optional manually annotated
panel and body boxes produce panel IoU, body-area coverage, and body-area
purity. `--ocr-layout` compares in-memory OCR word multisets between reference
and proposed body crops, reports recall, extra-word precision, line count,
edge-clipped words, and the readable-body gate. It emits JSON with no pixels or
recognized text. Adjacent frames and every transform of a source must share a
group and split; the tool rejects a group crossing development/holdout.
`experiments/panel_replay_2025_development.json` holds only metadata for the
existing repository screenshots. Public screenshots and their annotated replay
manifest were kept locally under ignored `.audition/tmp/`, not added to Git.

## Results on Windows, October 21, 2026

| Material | Structural result | Readable-body/crop result | Limit |
| --- | --- | --- | --- |
| 11 historical August 2025 screenshots | Nine `FOUND`, two `NOT_FOUND` | Body unannotated in replay | One session, near-identical pane/layout; two visible quest dialogues missed; development only |
| Five public dialogue screenshots | 5 `FOUND` | Five readable; provisional reference-crop OCR word recall and precision each 1.0; zero edge-clipped words. Body area coverage 0.908–0.970, purity 0.980–0.994. | Same screenshots informed geometry tuning; not holdout or transcript accuracy |
| Five public non-dialogue screenshots | Two `NOT_FOUND`, one `AMBIGUOUS`, two `FOUND` | Both false geometry proposals failed readable-body due to 9 and 14 clipped words respectively. | Only five negatives; no live false-start rate |
| Synthetic variations | Movement, independent panel size, color inversion, competing panels, absence, Stop and DPI invalidation exercised | Unit and hidden-UI checks | Generated art does not establish game generalization |

The two raw false positives are important: geometry by itself cannot decide
whether a similarly shaped shop or overlapping UI is quest dialogue. A replay
pass means only that this small development set was classified by **all**
configured gates. It is not permission to call the detector production safe.
One unlabeled 5120 x 1440 game frame was captured earlier without retaining
pixels; it cannot be scored as a quest example. LOTRO is offline for a server
shutdown, so this branch has no live quest, close, page-change, movement, or
audible-start qualification. G3's required 500 positives, 500 negatives and
100 interaction sequences remain open.

A synthetic 5120 x 1440 composited frame took 83–100 ms for five full-frame
structural detections on this Windows PC. This is CPU-only timing without game
contention or OCR/audio. It does not establish gameplay impact or latency.

## Public inspection provenance

The locally evaluated dialogue examples came from the
[font-size discussion](https://forums.lotro.com/index.php?threads/we-can-scale-the-size-of-quest-textes.13764/),
[wide-pane discussion](https://forums.lotro.com/index.php?threads/filling-in-the-world-of-middle-earth.71/page-13),
[compact dialogue image](https://i.imgur.com/bp3Usz2.jpg), and
[two difficulty bestowal images](https://forums.lotro.com/index.php?threads/please-bring-back-fast-paced-action-combat-from-before-u37-landscape-difficulty.3036/page-2).
The non-dialogue images include a
[quest journal and vendor set](https://www.lotrointerface.com/downloads/info303-FirefernsCraftingVendorandDressingRoom.html)
and LOTROInterface screenshots of a
[trait tree with overlapping panels](https://www.lotrointerface.com/downloads/full2823.jpg),
[another overlapping UI](https://www.lotrointerface.com/downloads/full3168.jpg), and a
[modern journal/UI showcase](https://www.lotrointerface.com/downloads/full4108.jpg).
The public images are local inspection material only. Ownership, training,
redistribution, and release-bundling rights were not established.

## Next qualification data

Capture owner-approved, locally labeled positive and negative frames across
current LOTRO clients, different UI scales, font sizes, languages, skins,
panel positions, panel sizes, and ultrawide layouts. Include quest bestowal,
progress, completion/turn-in, partial occlusion, close/reopen and page change;
include journal, map, inventory, shop, crafting, character, chat, tooltips,
loading and multiple-panel negatives. Label full panel and **all** narrative
words separately, plus reading eligibility. Hold out whole sessions/UI setups
and public-image source groups. Measure complete uncontaminated body crops,
false audible starts, missed dialogue, crop-to-audible time and Stop latency.
Borderless custom skins need a second candidate method or an explicitly
supported learned detector; the current line geometry can abstain on them.
