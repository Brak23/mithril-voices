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
window frame locally. The user first marks an approximate quest **body** area
in the overview, then zooms to native pixels and refines the crop with scrollbars.
The bounded crop goes to the already installed English Tesseract through standard
input, twice, with fixed preprocessing. The existing two-pass text gate reports
its decision. The preview stays open during OCR and shows pass progress, the gate
reason, a short explanation, and local raw OCR text. The user can cancel OCR or
retry a crop on the same captured frame without another game capture.
The probe does not save an image or OCR output, upload anything, play speech,
or change game files. The local console prints only gate metadata; raw OCR text
stays in the preview window.
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
2. Double-click `tools/Run-LOTRO-OCR-Probe.cmd` in the checkout from the
   signed-in desktop. It changes to the checkout itself and keeps its console
   open after the preview closes. Alternatively, in a **normal, non-admin
   PowerShell** from the checkout directory, run:

   ```powershell
   & ./.venv/Scripts/python.exe -u -m lvc.platform.windows.lotro_user_probe
   ```

3. Check the listed PID, title, executable path and client size. Enter the
   number for the intended LOTRO window, or press Enter to cancel. Type the
   displayed `CAPTURE N` phrase only if it is the intended window. Return to
   that game window within eight seconds and leave it focused until capture
   finishes. Do not grant new Windows permissions if prompted; stop and report
   the prompt instead.
4. The preview should appear above the game. In the overview, drag approximately
   around the quest body and click **Zoom to selection (native size)**. Use the
   scrollbars to pan, then drag around **complete visible quest body lines**,
   leaving space around edge words and excluding title, rewards, buttons and
   chat. Click **Preview OCR of selected body**. The same window shows progress,
   result and reason; **Retry crop from this frame** returns to the overview.
   Share only the gate reason, acceptance status, frame/crop size and a redacted
   accuracy description. Do not paste private chat or unredacted quest text.

The expected observations are whether an exact LOTRO window is discovered,
whether WGC delivers a current frame from that window, whether the preview
matches the intended quest panel, and whether two local OCR passes agree on
complete body text. A failure is useful evidence; record the displayed
`BLOCKED` reason without weakening the binding or widening capture scope.
The run is one frame with local crop retries. It does not enable narration.

## Validation boundary

The original handoff had successful native compilation and synthetic Python
tests. Its local synthetic receipt is
`../wp05-user-probe-synthetic.json` (31 passed, no skips). The no-argument native invocation returned
`BLOCKED:EXPLICIT_SELECTION_ARGUMENTS_REQUIRED`. No LOTRO window was selected
or captured by Codex. The owner later reported one real-game window selection,
one captured preview and a rejected OCR crop; the exact rejection detail was
not retained, so no specific OCR cause is asserted. The repair's own synthetic
tests cover ultrawide coordinate mapping, bounded crop, two-pass decisions,
cancel/timeout process reaping, repeated clicks and close behavior. On Windows,
the 11 focused probe tests and the 31-case vision-prep lane passed; an original
in-memory phrase also passed through the installed Tesseract and the unchanged
gate. The repaired GUI still needs the owner's retest. Crop correctness, DPI/UI scale,
quest-language performance and rights remain open WP-05 gates.

## Literal TSV parser repair after owner retest

The owner's second local Preview contained Tesseract TSV metadata interleaved
with recognized words. The defect was the probe's use of Python's default CSV
quoting rules for Tesseract's literal tab-separated records. A recognized leading
quotation mark could open a CSV quoted field and fold following physical TSV
rows into one OCR word. An original synthetic TSV fixture reproduced this
exact failure shape. The parser now treats quotation marks as OCR text, requires
the documented 12-column header/rows, ignores nonword structural records, and
fails closed on malformed rows. It keeps valid names and punctuation exactly as
recognized; there is no dictionary-based rejection or automatic word repair.

The existing two-pass gate still requires complete unclipped words, agreement,
all alphanumeric word confidences at least 40, and median confidence at least
85 per pass. The owner reported at least one word score below 40 in the same
trial, so the corrected parser may still abstain for genuine OCR uncertainty.
The UI now reports each pass's minimum and median score when that gate rejects.
No owner quest text or frame was used as a fixture or committed. A real-game
retest of this parser repair remains pending.

## Small-glyph confidence diagnosis after owner retest

The owner confirmed the TSV rows are gone. The new result had a word-confidence
minimum below 40 in the first pass and above 40 in the second. The first pass
uses the selected crop's native grayscale pixels; the second uses autocontrast
then 2x resizing. The 1200-pixel overview and scrollable native-size refinement
affect only the preview: OCR crops from the original captured frame. The user's
298x205 crop is in original frame pixels. No game image was retained here, so
its exact glyph heights and colors cannot be measured from this result.

The confidence floors come from R-TXT-002 and `contracts/defaults.json`:
every alphanumeric word at least 40 and each pass median at least 85. The
owner also identified a merged `I am` word in the OCR preview. This is an
accuracy error, not a dictionary issue. A low score can cause an honest
abstention, but a high score is not proof that the recognized words are right.

An ignored, local experiment rendered original text at small sizes in two
installed fonts and two contrast settings. It compared the current native/2x
pair with a proposed 2x grayscale/2x autocontrast pair. The proposed pair
accepted more cases but also accepted incorrect text: 6 of 7 accepted spacing
cases and 2 of 9 accepted protected-content cases differed from the source.
The existing pair also accepted one wrong spacing case. Thus the 2x change is
not qualified and was not applied. The two-pass thresholds and preprocessing
remain unchanged. The local result now lists the weakest recognized word guesses
and scores per pass, solely in the preview, to make the next diagnosis precise.
This probe still cannot establish accurate quest OCR or authorize narration.
