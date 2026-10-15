# Source reuse map

SOURCE_OBSERVED at `1c4c23f092fde34ce527ebb27309f57a8c5ec5bb`; choices below are
DESIGN_REQUIREMENT/planned, not executed extraction or compatibility proof.

| Source | Choice and boundary | Packet / independent tests |
| --- | --- | --- |
| main.py, src/engine_startup.py | Preserve legacy entry point; replace startup coordination in new host; never import old startup into host | WP-02/03/11; AT-010/017/077 |
| src/engine.py | Replace coordinator, shared queue/event, voice resolution ownership with pure immutable domain policy | WP-02; AT-001-019/070/072 |
| src/audio.py | Replace sounddevice ownership with sole Qt audio owner; retain legacy path unchanged | WP-04; AT-004/005/013/055/056 |
| src/ocr.py | Adapt preprocessing only after fixtures; replace destructive cleanup/exclusions and eligibility | WP-05; AT-030-034 |
| src/utils.py | Extract narrow template math only with provenance; replace desktop capture, cached geometry and watcher lifecycle | WP-05/07; AT-020-025/029/040-042 |
| src/calibrate_retail.py, src/calibrate_static.py, src/calibrate_echoes.py | Preserve reference behavior/history; new coordinate model and crop preview in vision adapter; no automatic qualification of legacy coordinates | WP-05/11; AT-041/043/066 |
| src/db_sqlite.py, data/ | Keep reference/inventory; optional corpus adapter only after rights and strict visible-span qualification | WP-17; AT-036-039/082 |
| src/models/ | Review shapes and preserve legacy tests; new frozen domain values independent of Qt/ML/singletons | WP-01/02; AT-077/078 |
| src/tts/base.py, kokoro.py, omnivoice.py | Retain engine knowledge behind worker protocol; remove global settings/playback/voice planning ownership | WP-03/06/12; AT-045-050/052/054/081 |
| src/tts/voice_library.py, text_splitter.py | Refactor stable realization identifiers and conservation-preserving chunker; do not assume current behavior meets v2 | WP-06/09; AT-051-053/083 |
| src/config/ConfigManager.py | Safe import converter only; replace live singleton with injected settings/state | WP-10/11; AT-057-059/065/066 |
| src/voice_lab/ | Preserve legacy Gradio path; new Qt UI shares the one renderer, not an extra audio route | WP-09/11; AT-018/055/067 |
| plugins/Dt192/ | Preserve author's namespace and provenance; optional new LVC bridge only after verified capabilities | WP-07; AT-026/027/028 |
| Windows/, Linux/, installer/ | Preserve legacy entry paths; replace new-product packaging with immutable fork-owned manifests/rollback | WP-14; AT-060-064/074 |
| tests/ | Keep legacy suite identifiable; classify source-only tests separately from real product checks | WP-00/01; AT-070/071/074/077 |
| .github/workflows/build.yml | Preserve during planning; later reviewed isolated QA lanes, no personal self-hosted runner | WP-01/14; AT-074 |
| experiments/ | Audit only; never execute notebooks during discovery or use them as production authority | WP-00; AT-077 |

Dependencies: upstream project metadata combines math/audio/ML/OCR/Gradio dependencies;
an existing uv.lock does not prove Windows runtime/worker isolation. New host, vision,
Kokoro and OmniVoice locks need separate actual clean-build evidence. The baseline
environment remains separate. No dependency installation occurred in this audit.

Import/file side effects: main.py sets model-cache environment paths;
utils imports instantiate ConfigManager and create directories; ConfigManager
initialization writes configuration; backend constructors load ML models and may
retrieve artifacts through their libraries. Tests must isolate configuration/user
data and block unexpected network/model loading before legacy imports execute.
