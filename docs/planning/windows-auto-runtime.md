# Mithril Automatic personal Windows trial

This packet connects selected-window capture, calibrated quest-pane detection,
two-pass local Tesseract OCR, the v2 page reducer, a warm offline Kokoro worker,
and the guarded Qt audio child. It leaves the existing `Mithril Voices.cmd`
manual launcher intact. `Mithril Auto Setup.cmd` remains the earlier
observation-only tool.

## Bryce's run sequence

1. Open LOTRO in the intended windowed or borderless size. Double-click
   **Mithril Automatic.cmd** on the Desktop. Select the verified retail LOTRO
   window. Choose a voice and the exact speaker, then click **Prepare voice**;
   wait for **Voice ready**. The first local model load takes several seconds.
2. Open a stock quest offer. Click **Capture open quest panel** and return focus
   to LOTRO within eight seconds. Draw a small distinctive static quest-pane
   border/emblem as the yellow anchor, and the complete quest body as the blue
   region. Use **Native-size refine** and scrollbars for exact edges. Click
   **Save regions**.
3. Close the quest pane. Click **Capture closed-pane control** and return to
   LOTRO within eight seconds. Show a journal or other non-quest surface; click
   **Capture journal/non-quest control** and return to LOTRO. Both controls must
   differ sufficiently from the quest anchor. If either fails, redraw a more
   distinctive anchor and repeat.
4. Return to a stock quest pane, click **Start automatic reading**, and return
   focus to LOTRO within eight seconds. The tool reads accepted stable new
   pages through the chosen local speaker. Try a same-NPC next page, close and
   reopen, then a non-quest surface. **Pause** fences capture and audio; click
   Start to resume a fresh session. **Stop** fences them and leaves the window
   open. Close the window to end its owned worker processes.

Capture is limited to the selected verified `lotroclient64.exe` window. The
native helper also requires that window to be foreground. A replaced,
minimized, resized, or DPI-changed window stops observation or requires new
calibration. OCR uncertainty abstains. A page change or confirmed closure
invalidates old OCR and requests speech cancellation before a new page can
read. The native helper returns one full selected-game frame in memory; the
app uses only the approved anchor and quest-body regions, then discards the
full frame. No screenshot, OCR text or gameplay content is saved or uploaded
by default. The geometry-only calibration and metrics-only summary remain local;
auto voice/speaker preferences are stored separately from manual preferences.

## Verification and current limits

Synthetic owned-window tests cover the qualification controls, duplicate and
changed pages, stale OCR, close, pause, resized/DPI windows, unavailable OCR,
and identity failure before native capture. The real local software smoke uses
a generated image, two-pass Tesseract, a warm Kokoro worker, verified private
WAVs and a silent Qt sink. It also cancels an in-flight generation and a
submitted silent-audio unit. This is **not** a LOTRO gameplay or physical
speaker test.

One warm synthetic run submitted audio at 1,875 ms after Start, following an
8,922 ms initial voice warmup; another submitted at 2,156 ms. This measures
software audio submission, not audible onset. Foreground game capture cadence,
actual speaker buffering and repeat-run latency can raise the live time.
The detector uses a user-selected anchor and two negative in-session controls,
not the held-out 500-positive/500-negative G3 qualification set. Bryce's live
run must verify it avoids non-quest speech, reads only complete quest text,
and cancels immediately on real page changes/closure. Production G3 remains
open, including game impact, session soak, rights and physical audio evidence.
