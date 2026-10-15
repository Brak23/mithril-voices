# Windows WP-01 foundation slice

This branch extends the first contract-data component after the Windows
baseline PR. It keeps the archived v2.0 contract package unchanged. The full
WP-01 and G1 gates remain open.

`contracts/runtime-preferences.schema.json` accepts only a versioned delta
for `audio.follow_system_default` and `privacy.history_enabled`. It rejects
other settings, including capture scope, model/profile activation, operational
limits and unverified device IDs. The original defaults schema still requires
the exact shipped snapshot. A future host must authorize and apply preference
changes; validation does not change runtime state.

The synthetic support controls use a manual clock, held child replies and a
passive sink recorder. The recorder deliberately logs stale writes. It cannot
make a broken coordinator look safe by filtering writes on its behalf. The
original synthetic fixture manifest records hashes and independent expected
outcomes for AT-001, AT-002 and AT-010, all in the development split. These
cases have not been run through product coordination code.

Run in the isolated development Python 3.12 environment with the pinned
development tools:

```text
python tools/qa.py --suite contract
python tools/qa.py --suite foundation
ruff check tools/validate_contracts.py tools/qa.py tools/windows_qt_smoke.py tests/v2
pyright --pythonpath <DEV_PYTHON> tools/validate_contracts.py tools/qa.py tests/v2/support.py
```

The separate Qt development probe uses the observed official PyPI PySide6
6.12.0 wheel on Windows Python 3.12.10. `python tools/windows_qt_smoke.py`
starts a real QApplication event loop and a controlled asynchronous QProcess
child without launching LOTRO, capturing a window or opening an audio sink.
PySide6 PDF/WebEngine arrived as metapackage dependencies; they are not chosen
runtime components. Packaging and redistribution require separate dependency
and rights review.

Current results and raw sanitized JUnit reports are in
`docs/evidence/wp01/windows-foundation-summary.json`. The inherited workflow
still targets main/tag events and builds/releases the legacy installer; it was
not run. Full dependency locks, fake-to-real coordinator integration, mutation
checks and hardware/device evidence are next gates. `quick`, `replay`,
`windows`, `gpu`, `package` and `release` remain BLOCKED/NOT_RUN.
