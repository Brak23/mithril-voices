# Mithril Automatic personal Windows trial

This packet connects selected-window capture, calibrated quest-pane detection,
local Windows OCR, the v2 page reducer, a warm offline Kokoro worker,
and the guarded Qt audio child. It leaves the existing `Mithril Voices.cmd`
manual launcher intact. `Mithril Auto Setup.cmd` remains the earlier
observation-only tool.

## Bryce's run sequence

1. Open LOTRO in the intended windowed or borderless size. Double-click
   **Mithril Automatic.cmd** on the Desktop. Select the verified retail LOTRO
   window. Choose a voice and the exact speaker, then click **Prepare voice**;
   wait for **Voice ready**. The first local model load takes several seconds.
2. Open a quest dialogue window. Click **1. Capture open quest window** and
   return focus to LOTRO within eight seconds. With **2. Yellow: small border
   detail**, draw around one small decorative corner or border mark that does
   not contain the changing title or dialogue. Do not outline the whole quest
   window in yellow. Switch to **3. Blue: all dialogue words** and draw around
   every dialogue line inside the pane without overlapping yellow. Both boxes
   stay visible; redrawing one color keeps the other. Use **Native-size refine**
   and scrollbars if needed, then click **4. Save yellow + blue boxes**. The
   app names the box to correct if it is too large, too small, or overlapping.
   A new immutable build can offer saved boxes for the same LOTRO installation,
   frame/client size and DPI. Inspect them on a fresh capture before Save. The
   internal LOTRO UI scale cannot be verified automatically, so redraw boxes
   if its pane layout changed. Saved boxes do not restore the two safety
   controls or arm automatic speech.
   **Preview moved panel (speech off)** can display a provisional extent and
   body box after moving the pane, if the anchor has distinctive detail. Its
   similarity number is not a calibrated quest probability. This preview never
   authorizes speech; the current trial still speaks from the saved regions.
3. Close the quest window. Click **5. Capture with quest closed** and return to
   LOTRO within eight seconds. Show a journal or inventory without quest
   dialogue; click **6. Capture journal or inventory** and return to LOTRO.
   Both safety samples must show that the yellow detail is absent. If one
   fails, check the displayed scene and recapture; if it is correct, redraw
   yellow on a more distinctive border detail and save again.
4. Return to an open quest dialogue, click **Start automatic reading**, and return
   focus to LOTRO within eight seconds. During automatic reading the Windows
   capture outline can remain steadily visible; it should disappear on Stop.
   The tool reads accepted stable new
   pages through the chosen local speaker. Try a same-NPC next page, close and
   reopen, then a non-quest surface. **Pause** fences capture and audio; click
   Start to resume a fresh session. **Stop** fences them and leaves the window
   open. Close the window to end its owned worker processes.

Capture is limited to the selected verified `lotroclient64.exe` window. The
native helper also requires that window to be foreground. A replaced,
minimized, resized, or DPI-changed window stops observation or requires new
calibration. OCR uncertainty abstains. A page change or confirmed closure
invalidates old OCR and requests speech cancellation before a new page can
read. Within one quest interaction, accepted words are also compared after
space/case normalization so minor pixel changes cannot narrate the same text
again. The native helper returns one full selected-game frame in memory; the
app uses only the approved anchor and quest-body regions, then discards the
full frame. No screenshot, OCR text or gameplay content is saved or uploaded
by default. The geometry-only calibration and metrics-only summary remain local;
auto voice/speaker preferences are stored separately from manual preferences.

Automatic text admission runs the verified local Windows OCR helper on the
body and on a padded version. Empty, invalid or differing word sequences
abstain, as does high-contrast content touching the crop edge. Padding checks
input stability; it cannot reveal text omitted outside the crop. This helper
does not return word confidence. Manual mode still puts Windows OCR into an
editable draft for human confirmation; automatic mode uses panel evidence and
fail-silent checks. The metrics-only summary records the actual backend name
`windows_media_ocr_dual_variant`, never recognized words.

## Verification and current limits

Synthetic owned-window tests cover the qualification controls, duplicate and
changed pages, stale OCR, close, pause, resized/DPI windows, unavailable OCR,
and identity failure before native capture. The real local software smoke uses
a generated image, Windows OCR, a warm Kokoro worker, verified private
WAVs and a silent Qt sink. It also cancels an in-flight generation and a
submitted silent-audio unit. This is **not** a LOTRO gameplay or physical
speaker test.

One Windows OCR warm synthetic run submitted audio at 2,719 ms after Start,
following 9,187 ms of initial voice warmup. Earlier 1,828–2,156 ms runs used
the former Tesseract backend. This measures
software audio submission, not audible onset. Foreground game capture cadence,
actual speaker buffering and repeat-run latency can raise the live time.
The detector uses a user-selected anchor and two negative in-session controls,
not the held-out 500-positive/500-negative G3 qualification set. Bryce's live
run must verify it avoids non-quest speech, reads only complete quest text,
and cancels immediately on real page changes/closure. Production G3 remains
open, including game impact, session soak, rights and physical audio evidence.

## Persistent capture and local box profile

Bryce's first guided run saved a metrics-only summary with nine successful
frames and one capture failure over about nine seconds. The UI displayed the
initial switch-to-game instruction before each requested frame, and the
one-shot native helper created a fresh Windows Graphics Capture session per
frame. Those behaviors explain the repeated instruction and are consistent
with a flashing capture outline. The summary does not prove the foreground
state at the moment of the failure.

The automatic observation path now owns one exact-window native capture
session from Start through Stop. It checks the selected HWND, process, start
time, executable and foreground state at startup and each requested frame.
Capture, identity or focus failure ends that session and pauses automatic
reading after one failure. There is no silent restart. Calibration and safety
sample buttons continue to use bounded one-shot captures.

Only the two rectangle coordinates and binding geometry persist in
`mithril-auto-state/calibration-<hash>.json` outside immutable builds. A
previous build's geometry-only file can be imported once as a suggestion
when frame/client size and DPI match; that older file has no installation
identity, so the user must check and save the boxes to bind them to the
current installation.
Pixels, OCR text, reference pixels, negative-control samples and armed state
are not stored in this profile. New HWNDs and PIDs can reuse keyed saved
rectangles; resolution, client size, DPI or install-path changes cannot. Every new session
still requires a fresh open-panel capture, Save and both negative controls.

The stream protocol, single-session ownership, cancellation and profile
binding are covered by synthetic tests. A positive Windows Graphics Capture
test of this stream helper against an owned window remains to be completed
outside the restricted sandbox. The live LOTRO path and its effect on the
game remain unqualified until Bryce elects to retest.
