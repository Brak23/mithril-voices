# Opt-in LOTRO observation setup

The separate `Mithril Auto Setup` launcher uses only the existing reviewed
selected-window native helper. It inventories verifiable `lotroclient64.exe`
windows, requires a user selection, and starts capture only when the user clicks
Capture or Start. The selected window must be foreground for each native frame.
Stop kills the owned capture/OCR children and invalidates late results. No
gameplay input, audio playback, model inference, or desktop-wide capture occurs.

## Bryce's short live sequence

1. In the current windowed/borderless LOTRO session, open a stock quest offer.
   Keep the intended resolution, DPI, graphics mod and UI scale. In the Desktop
   `Mithril Auto Setup` launcher, choose the verified LOTRO row.
2. Click **Capture open quest panel**, return focus to LOTRO within eight
   seconds, then return to Mithril. Draw a small static quest-pane border or
   emblem as the yellow **anchor**. Draw only complete quest body lines as the
   blue **body**, excluding buttons, rewards and chat. Click **Save regions**.
3. Click **Start observation (no speech)** and return to LOTRO within eight
   seconds. Show one new page with the same NPC, close and reopen the quest
   panel, then show a non-quest surface such as the journal. Return to Mithril
   and click **Stop**. The window displays candidate text and explicit OCR
   abstention reasons. Tell us whether it reported each change/close correctly.

The saved private calibration contains only rectangle coordinates, frame/client
dimensions and DPI. The anchor pixels are reacquired in memory each session.
The private latest-run summary contains counts/timing only. Screenshots and OCR
text are not saved, logged or uploaded. If the game window size, DPI, UI skin or
UI scale changes, capture again and inspect/recalibrate the rectangles. This
observation tool does **not** authorize automatic speech: its anchor comparison
threshold is diagnostic, without a held-out retail detector profile.

`Mithril Voices.cmd` remains the manual reading path. Qualification still
needs correctly labeled positive/negative LOTRO screens, synthetic-to-real
callback integration, exact speaker audio/Stop measurements, and game impact
evidence before Auto can be enabled. One observation session is for calibration,
not the 500-positive/500-negative G3 acceptance study.
