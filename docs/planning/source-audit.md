# Mithril Voices: source audit for implementation planning

Status: read-only source audit reconciled with the completed v2.0 requirements
package. See [the implementation plan](implementation-plan.md) and
[the specification](../design-v2/IMPLEMENTATION_SPEC.md). This audit is source
evidence, not the governing specification or a reproduced runtime failure report.

## Baseline and provenance

- Fork: https://github.com/Brak23/mithril-voices
- Upstream: https://github.com/Thelukepet/Khazad-Voice-TTS
- Inspected commit: `1c4c23f092fde34ce527ebb27309f57a8c5ec5bb` on `main`.
- Public GitHub fork; the cloned `origin` is the fork and `upstream` is the source.
- Preserve the upstream history, authorship, README credits and LICENSE.
- `LICENSE` contains Apache 2.0; `pyproject.toml` declares MIT. This is a
  release-blocking metadata uncertainty to clarify before packaging a new release.
  No license metadata has been changed in this audit.
- Model weights, voice references, plugin code and game-derived data require
  separate provenance review before redistribution; the root license alone does
  not establish their redistribution terms.

## Verified code map and candidate regression coverage

These are static observations, not measured production failure rates. Candidate
tests below must be reconciled with the complete requirements package.

| Area | Source evidence | Planning implication / candidate acceptance test |
| --- | --- | --- |
| Retail event handling | `src/engine_startup.py`, `EngineStartup.start_retail`: log callback retries capture, calls blocking `process_retail`, then suppresses the same NPC for two seconds | Separate observation from narration; replay two different pages from the same NPC during speech and prove the later page is observed independently |
| Cancellation ownership | `src/engine.py`, `NarratorEngine.stop` and `_start_streaming`: shared event set by Stop then cleared for a new job; producer shares queue; untagged `None` sentinel | Define immutable request identity and terminal cancellation; delay an old producer until a newer request starts, then prove old audio and completion cannot affect the newer request |
| Backpressure | `src/engine.py`, constructor: unbounded `queue.Queue()` | Specify capacity, supersession and overflow policy; prove memory/work remains bounded under event bursts |
| Audio boundary | `src/audio.py`, `play_audio`: starts `sd.play` before checking cancellation in the polling loop | Require an atomic current-generation check at the audio owner; exercise Stop racing playback start and record Stop-to-silence separately on real hardware |
| Watcher lifecycle | `src/utils.py`, `watch_npc_file`: sleeps only when file missing; reads only when size increases; invokes callbacks synchronously | Test idle polling budget, truncate/rotate/recreate behavior, shutdown and callback exceptions; no runtime measurements have been taken |
| OCR preservation | `src/ocr.py`, `clean_ocr_errors`: global `1` to `I`, `Ore` to `Orc` and other replacements; `run_name_ocr` also replaces `1` | Preserve raw text; create synthetic numeric and legitimate-word fixtures and require context-scoped corrections |
| Quest substitution | `src/db_sqlite.py`, `match_quest_text`: chooses best fuzzy body match, accepts score >=0.4 after title resolution | Require evidence and ambiguity policy; test similar titles/stages, partial viewport, missing corpus, unresolved variables and wrong-segment abstention; similarity is not probability |
| Voice persistence | `src/engine.py`, `_resolve_voice`: loads memory with backend ID but calls `save_npc_memory(self.memory, self.mode)` without backend; utility defaults to OmniVoice | Test Kokoro/OmniVoice separation across restart and migration; preserve existing user mappings |
| Voice identity | `src/tts/kokoro.py` chooses randomly; `src/tts/voice_library.py` derives numeric IDs from enumerated files | Define stable asset identity and deterministic assignment; adding a library entry must not silently recast existing NPCs |
| Streaming test gap | `tests/test_engine.py`, `test_start_streaming_basic`: creates inputs and asserts they exist; never calls `_start_streaming` | Build a real lifecycle test with fake synthesis/audio, barriers and timeouts, without AI model downloads |
| Installation | `installer/setup.py`: source URL points at upstream `main.zip`, uv URL uses latest; Windows/Linux install scripts invoke package downloads | Define fork-owned versioned release manifests, checksums and rollback before distribution; do not ship an installer that replaces fork code with upstream main |
| Dependency claims | `pyproject.toml` permits Python >=3.10 while README/install guidance uses 3.12; `uv.lock` exists; many dependencies have broad ranges | Qualify one supported baseline and verify lock applicability; no claim of reproducible installation yet |
| Existing CI | `.github/workflows/build.yml` tests, builds installer on PRs/main and publishes tags; test install uses `.[test]` including base dependencies | Plan a lightweight isolated regression lane and separate release gates; do not enable or invoke workflows as part of planning |

## Reuse boundaries to reconcile with final requirements

- Keep initially behind adapters: `src/tts/base.py`, `kokoro.py`, `omnivoice.py`,
  calibration modules, capture helpers, quest/NPC models and database access.
- Refactor incrementally: observer lifecycle, text validation, voice identity,
  configuration/persistence and backend boundaries.
- Replace coordination and audio ownership only after contracts and deterministic
  tests establish the intended behavior.
- V2 explicitly targets the new runtime at Windows 11 x64. Preserve legacy
  Windows/Linux/Echoes code, without claiming the new host is qualified on Linux
  or macOS.
- Keep legacy user data recoverable; do not point experimental migration code at
  a live `~/.khazad-voice-tts` directory during tests.

## Pending next steps

1. Review this audit together with the adopted v2 contracts and execution map.
2. Complete the remaining WP-00 bootstrap/baseline/rights obligations in their own
   scoped task; do not mark G0 passed from source review alone.
3. Keep application implementation, dependency installation, model downloads,
   game changes, workflows and paid services outside this planning task.

## Validation performed

Repository metadata, source files, tests, installer scripts and workflow were read.
The fork was identical to the pinned upstream when cloned. No upstream code,
tests, installer, model or workflow was executed. Runtime baseline results,
performance improvements and test pass counts remain unmeasured.
