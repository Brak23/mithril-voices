# Local Kokoro CPU audition (WP-06 slice)

This is an isolated Windows voice audition, not the finished WP-06 manual reader
or a release bundle. It opens no game window or audio device. Its six passages
are original synthetic fixtures; a saved WAV is **generated, not listened to**.
The production Qt host, actual Stop-to-silence, game OCR, and voice preference
remain separate qualification work.

## Pinned inputs and rights boundary

Use CPython 3.12 x64 and the hash-locked PyPI wheel set in
`docs/runtime/kokoro-cpu-windows-py312.lock.txt`. The direct version constraints
are beside it in `.in`; the lock contains SHA-256 hashes for each resolved
distribution. This audition used Kokoro and Misaki 0.9.4, PyTorch 2.14.1 CPU,
spaCy 3.8.11, Transformers 4.53.3, SciPy 1.16.2, and eSpeak loader 0.2.4.
The wheel-only lock contains 86 resolved packages, including a direct `click`
pin needed by spaCy's Windows import. The English spaCy model is a separate
official wheel.

The model repository is
[`hexgrad/Kokoro-82M` revision `f3ff3571791e39611d31c381e3a41a3af07b4987`](https://huggingface.co/hexgrad/Kokoro-82M/tree/f3ff3571791e39611d31c381e3a41a3af07b4987).
Only these files are used:

| Local file | SHA-256 |
| --- | --- |
| `config.json` | `5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f` |
| `kokoro-v1_0.pth` | `496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4` |
| `bf_emma.pt` | `d0a423deabf4a52b4f49318c51742c54e21bb89bbbe9a12141e7758ddb5da701` |
| `bm_fable.pt` | `d44935f3135257a9064df99f007fc1342ff1aa767552b4a4fa4c3b2e6e59079c` |
| [`en_core_web_sm-3.8.0-py3-none-any.whl`](https://github.com/explosion/spacy-models/releases/tag/en_core_web_sm-3.8.0) | `1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85` |

Kokoro code/model and Misaki identify as Apache-2.0; the spaCy model release
identifies as MIT. The eSpeak loader Python wrapper is MIT but [its bundled
eSpeak NG native code is GPL-3.0-or-later](https://github.com/espeak-ng/espeak-ng#license-information).
Source voice/data provenance, the spaCy model's training data, all transitive
notices, and a redistribution decision still need formal review before a public
installer. None of these model, native, or generated audio files belongs in Git.

## Reproduce on the approved PC

From the repository root, with `uv` and Python 3.12 available, create a task-only
venv and use an application-owned cache location. The assets must first be
fetched individually from the pinned official revision and checked against the
hashes above. The script never downloads models.

```powershell
New-Item -ItemType Directory -Force .audition\assets, .audition\tmp | Out-Null
$env:UV_CACHE_DIR = (Join-Path (Get-Location) '.audition\uv-cache')
$env:UV_NO_CONFIG = '1'
uv venv .audition-venv --python python
uv pip sync --python .audition-venv\Scripts\python.exe --require-hashes --only-binary :all: --default-index https://pypi.org/simple docs\runtime\kokoro-cpu-windows-py312.lock.txt
uv pip install --python .audition-venv\Scripts\python.exe --no-index --no-deps .audition\assets\en_core_web_sm-3.8.0-py3-none-any.whl
.\.audition-venv\Scripts\python.exe -m lvc.tts.kokoro_worker --assets .audition\assets --fixtures tests\v2\fixtures\pregame_passages.json --output .audition\wavs
```

`uv pip sync` removes the separately installed spaCy language wheel if rerun;
restore that local wheel afterward. `KokoroCpu` verifies runtime versions and
all four model/voice hashes, requires the spaCy package and eSpeak fallback,
sets Hugging Face/Transformers offline mode, disables spaCy's download helper,
and passes explicit local paths to Kokoro. A missing component fails before
synthesis. The parent process runs one CPU worker per voice and reaps it on
cancel/timeout; each worker records a generation and writes complete WAVs
atomically. The parent admits results only after matching receipts, hashes, and
48 kHz mono PCM validation. This parent/child seam does not yet implement
production QProcess/Job Object containment or actual renderer cancellation.

The resulting WAVs and receipts live under `.audition/wavs/<generation>/`,
which is ignored by Git. The first-unit timing starts after text phonemization
and model load; it does not measure audible onset or end-to-end application
latency. Inspect the receipt for file hashes, frame counts, and per-passage
render times. Bryce still needs to listen and choose a narrator; neither
candidate has been enabled as a production default.

## Windows audition evidence (15 October 2026)

The pinned four model files and the spaCy wheel matched the SHA-256 values
above. The wheel-only PyPI sync completed, and all required imports ran in
the isolated CPython 3.12.10 environment. A first spaCy import exposed a
missing `click` declaration; the final lock pins it explicitly. The audited
machine had about 30 GB available before setup. The resulting isolated venv
occupied about 1006 MiB, the separate download cache 977 MiB, and approved
model/pronunciation assets 325 MiB. These are local build footprints, not a
shipping size estimate.

The two CPU workers generated **12 unheard WAVs**, six per voice. The Emma
set totals 39.52 seconds of PCM; Fable totals 41.42 seconds. Median per-passage
render times after model load and phonemization were 1038 ms and 1078 ms,
respectively. These six samples per voice cannot establish latency p95 or
voice quality. Every receipt and complete 48 kHz mono 16-bit WAV passed
parent-side hash, frame-count, and bounded-file validation. The generated
files remain in the ignored local `.audition/wavs/<generation>/` directory.

The new independent guards passed 8/8 tests, including actual Windows child
termination and reaping after a generation change. The existing voice-prep
lane passed 41/41 and contract lane 43/43 after setting the sandbox temporary
directory to `.audition/tmp`. Ruff and Pyright passed for the new modules.
The broad quick/Windows/device/game/release suites and physical listening
tests have not run. An installed-wheel metadata scan recorded 87 packages
including the separate spaCy model; ten did not expose a machine-readable
license expression or license classifier, so the public package rights gate
remains open.
