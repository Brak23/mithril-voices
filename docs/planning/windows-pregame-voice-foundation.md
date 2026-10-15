# Local pregame voice foundation

This slice prepares voice and speech decisions without launching LOTRO,
capturing a window, downloading a model, loading a model, or playing audio.
It is a local branch only. It does not complete WP-06, WP-09, WP-10, G1 or G2.

## Implemented seams

- `lvc/voice/text_plan.py` stores raw OCR, accepted display text and speech
  text separately. A versioned, provenance-bearing data-only lexicon applies
  literal whole-word/phrase matches to speech text and records source spans.
  Numeric and negation token changes are rejected. This is a structural guard,
  not proof that a proposed pronunciation is correct; real lexicon entries
  still need owner review. The bundled English lexicon is intentionally empty.
  Its strict JSON loader rejects unknown executable-looking fields. The
  lexicon content digest changes cache identity. Only an accepted OCR decision
  can enter the automatic speech-plan helper.
- The deterministic `sentence-1` chunker retains exact source offsets. Joining
  units reproduces the speech text byte-for-byte at the Python string level,
  including repeated sentences, whitespace, punctuation and line breaks.
  Units are capped at 280 Unicode code points; an adapter may supply its
  separately verified token counter/limit. An overlong unbroken word fails
  instead of being truncated.
- `lvc/voice/assignments.py` persists an approved realization ID, engine and
  asset digest on a caller-owned SQLite connection before first use. A stable
  trustworthy speaker key retains its voice when catalog entries are added.
  An unknown/untrusted speaker resolves to the fixed narrator. A missing or
  changed assigned realization blocks for explicit replacement. Only the
  storage owner should call this module; there is no app-level voice UI yet.
- `lvc/voice/cache.py` keys complete WAV units by exact speech text, locale,
  model/runtime, realization/asset, lexicon digest/version, overrides, speed,
  style, chunker and output version. It validates format, duration, payload,
  silence and checksum. Same-directory temporary files are flushed and
  atomically renamed. A torn two-file update becomes a cache miss. Cache get
  and put recheck caller-supplied current-request authority, and the existing
  `AudioGate` still performs the final generation check before any sink write.
  Corruption becomes a miss, not a playable hit. Cache budget, eviction,
  disk-floor policy and startup reconciliation remain WP-10 work.
  `AudioSubmission` now marks cache as its source so the Qt owner can apply
  its existing final gate to a cache hit; a fake-backend Stop case checks that
  old cached PCM stops writing after the generation fence.
- `lvc/voice/artifacts.py` checks explicit local audition prerequisites by
  path, SHA-256, provenance and recorded approval. It does not import Kokoro,
  execute model code, download assets, or choose a voice.

The original six fantasy-style passages in
`tests/v2/fixtures/pregame_passages.json` exercise text conservation,
Unicode, repeated wording, punctuation, numbers, negation and line breaks.
Synthetic tests also cover persistent casting, catalog insertion, missing
voices, corrupted/truncated cache entries, stale lookup/worker responses, and
the existing audio generation fence. These tests do not certify spoken word
fidelity or production Stop timing.
The Windows `voice-prep` lane records 41 passing tests with no failures or
skips in the local receipt `../wp06-pregame-voice-synthetic.json`. Ruff and
Pyright checks passed. The receipt's application runtime acceptance is
`NOT_RUN`.

## Model and audition gate

The task venv contains no installed `kokoro`, `misaki`, `torch` or OmniVoice
runtime. The repository contains reference recordings, but their rights and
transcripts are not qualified for this work; none were loaded or played.
The v2 default `kokoro_cpu` is a design choice, not a selected production
voice. A real audition needs the owner's separate approval of exact local
artifacts and sources: Kokoro model weights, a specific voice weight file,
the pinned Python/native runtime lock, and pronunciation resources. Record
each artifact's immutable hash, version, license/attribution evidence and
approved use. Select the actual voice ID from audited files only after this
review. The official [Kokoro model card](https://huggingface.co/hexgrad/Kokoro-82M)
and [repository](https://github.com/hexgrad/kokoro) are candidate source
references, not authorization to fetch or install them.

After approval, run one offline Kokoro candidate at a time on the six original
passages through the shared worker and audio owner. Compare omission,
repetition, pronunciation, voice consistency, warm latency and Stop behavior;
then choose a narrator. Keep any premium comparison and its separately
licensed weights conditional. The code does not claim either model sounds
better without an audition.

## Next integration work

Wire the audited CPU model worker into the strict IPC, text plan, cache and
shared Qt audio owner; add a user-visible audition/voice selection path and
app storage migrations. Retest cached and uncached Stop on the actual endpoint.
The first game passage remains a separate later step, after Bryce starts LOTRO.
