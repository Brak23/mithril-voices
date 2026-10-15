# WP-05 user-run LOTRO window and OCR probe

## Current evidence

The owner supplied a successful result for the **application-owned fixture window**
from normal PowerShell on 2026-10-15. It reported WGC supported,
one frame received, identity verified, and negative checks passed. This is
user-reported execution, summarized with provenance in
`docs/evidence/wp05/user-run-owned-window.json`; it was not reproduced in the
managed Codex execution context. That context returned `0x80070005` at the WGC
support query. Neither result qualifies LOTRO capture or OCR.

## Prepared next step

`lvc/platform/windows/lotro_user_probe.py` is a manually invoked, local-only
probe. It lists visible top-level windows whose native process executable is
`lotroclient64.exe`. The user chooses one numbered candidate and then types
`CAPTURE N`. The native helper receives that candidate's HWND, PID, process
creation tick and full executable path. It rechecks them, visibility and
foreground state before and during Windows Graphics Capture, requests one
frame from that exact HWND, and closes the session. It has no monitor capture
path. A missing or changed identity, missing foreground, minimized window,
timeout, invalid dimensions or unavailable WGC stops the run.

The helper pipes RGB pixels to Python in memory. Python shows the selected
window frame locally so the user can drag a quest **body** crop. The crop goes
to the already installed English Tesseract through standard input, twice,
with fixed preprocessing. The existing two-pass text gate reports its decision.
The probe does not save an image or OCR output, upload anything, play speech,
or change game files. The local console does display raw OCR Preview text.
The native helper is a local Build Tools build pinned by SHA-256 in the Python
entrypoint. It is not a distributed release artifact.
The prepared executable is under the local task root at
`test-tmp/lotro_frame_probe.exe`
with SHA-256
`3e64737ea1feb5805e5f8430546b7c4d4566a6b40b97635502fad90db277d9ba`.
If it is missing or differs, the Python entrypoint stops before capture; do
not substitute an unreviewed executable.

## Owner's run checklist, when ready

1. Launch the retail 64-bit LOTRO client yourself in windowed or borderless
   mode. Open one quest panel with visible body text. Hide chat or other
   private content before capture. Leave the game running.
2. In a **normal, non-admin PowerShell** on the signed-in desktop, run:

   ```powershell
   Set-Location '<local Mithril Voices checkout>'
   .\.venv\Scripts\python.exe -m lvc.platform.windows.lotro_user_probe
   ```

3. Check the listed PID, title, executable path and client size. Enter the
   number for the intended LOTRO window, or press Enter to cancel. Type the
   displayed `CAPTURE N` phrase only if it is the intended window. Return to
   that game window within eight seconds and leave it focused until capture
   finishes. Do not grant new Windows permissions if prompted; stop and report
   the prompt instead.
4. In the local preview, drag around **only visible quest body text**, avoiding
   clipped lines, title, rewards, buttons and chat. Click **Preview OCR of
   selected crop**, or cancel. The console shows the raw OCR and two-pass gate
   reason. Share only the gate reason, acceptance status, frame/crop size and a
   redacted accuracy description. Do not paste private chat or unredacted
   quest text into this thread.

The expected observations are whether an exact LOTRO window is discovered,
whether WGC delivers a current frame from that window, whether the preview
matches the intended quest panel, and whether two local OCR passes agree on
complete body text. A failure is useful evidence; record the displayed
`BLOCKED` reason without weakening the binding or widening capture scope.
The run is one frame, one crop, one OCR Preview. It does not enable narration.

## Validation boundary

This handoff has only a successful native compilation and synthetic Python
tests so far. The local synthetic receipt is
`../wp05-user-probe-synthetic.json` (31 passed, no skips); Ruff and Pyright
passed. The no-argument native invocation returned
`BLOCKED:EXPLICIT_SELECTION_ARGUMENTS_REQUIRED`. No LOTRO window was selected
or captured by Codex. Window
discovery, WGC delivery in the real game, crop correctness, DPI/UI scale,
quest-language performance and rights remain open WP-05 gates.
