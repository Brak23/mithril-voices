# WP-06 manually confirmed quest read

## Scope and owner result

The owner reported that Windows OCR appeared accurate on one quest in the
WP-05 preview. This is one user observation, not measured accuracy across quest
panels. This packet completes a manual read path for the currently selected
single frame. It does not enable automatic narration or qualify broader OCR.

The preview now runs Windows OCR first. Tesseract is an optional comparison
checkbox, initially off. Source guesses remain separate from the editable draft.
The draft starts with Windows OCR when available; the owner checks the image,
edits the draft as needed, and explicitly confirms it. An edit, crop change,
new OCR attempt, voice or speaker change, retry, or close stops an active read;
text changes and OCR actions also invalidate confirmation. Read is available
only after current confirmation, a voice and an exact output speaker are chosen.

Only the two already installed, pinned local Kokoro voices are offered: Emma
and Fable. There is no inferred NPC identity in this one-frame flow, so the
voice is an explicit choice from `VoiceCatalog`. A child in `.audition-venv`
renders bounded chunks offline. A second child in `../qt-dev-venv` validates
complete WAV bytes and drives the existing Qt audio owner and selected
`QAudioSink`. Stop revokes the generation and fences playback; the host can
terminate its owned child Job Object if shutdown does not finish. No model is
loaded by Tk. The text goes through a pipe after Job Object assignment; it
does not enter process arguments or console logs.

Private temporary WAVs live in ignored `.audition/tmp/manual-read` and are
removed at the end of a read. **Keep private local audio cache** is initially
off. When selected, the existing content-addressed complete-WAV cache stores
verified WAV and metadata in ignored `.audition/manual-cache`. The source text
is part of the cache key input but is not stored as plaintext metadata. A user
who wants no retained audio should leave the checkbox off. No network service,
new model download, game file modification, or new permission is involved.

## Windows development evidence

On this Windows PC, 18 focused synthetic preview/manual tests passed. The
installed Emma and Fable renderers each produced an original synthetic phrase;
the silent Qt backend admitted and drained each verified WAV and reported
completion. A
two-unit synthetic WAV test checked ordering; a bad hash and an external path
were rejected before backend construction. A fresh synthetic render was stopped
while its owned child was active and did not complete. A cached silent read was
stopped at unit start, reported Stop without completion, and a subsequent read
completed. The silent backend opens no speaker. Ruff and Pyright checks passed
for changed Python files. These checks do not establish audible quality,
physical device selection, real-game capture, or OCR accuracy.

## Owner's next manual check

1. Launch LOTRO yourself, show one quest body with no private chat visible,
   then run `tools/Run-LOTRO-OCR-Probe.cmd` from this checkout. Select the exact
   LOTRO window and type its displayed `CAPTURE N` phrase. Return focus to the
   game for the one-frame capture.
2. Crop the quest body at native size and press **Preview OCR of selected
   body**. Check the Windows source against the visible image. Edit the draft
   where necessary; the Tesseract checkbox is optional for diagnosis.
3. Choose **Emma** or **Fable**, choose the intended speaker explicitly, and
   press **Confirm corrected text for this preview**, then **Read confirmed
   text**. Press **Stop speech** partway through, confirm audio stops, then
   press Read again. Leave the cache checkbox off unless you want to retain
   local WAVs for replay.
4. Report whether the selected speaker was correct, speech matched the
   confirmed draft, Stop was prompt, replay completed, and any displayed
   reason code. Do not share the screenshot or quest text.

The application and native helper must be run from the existing checkout on
the signed-in desktop. A new game frame requires closing the preview and
repeating the explicit window selection/capture command. The owner has not
yet reported an audible real-game read; this packet remains at manual
end-to-end check pending. Model and corpus rights remain separate gates.
