# Personal Windows installation of the confirmed manual flow

This is a private installation for the existing Gaming PC. It copies a
versioned source snapshot beside this repository and places a launcher on the
Desktop. The snapshot links to the already installed local Python, Qt and
Kokoro environments and the previously approved local model/voice files. It
does not include those assets for public redistribution, install anything new,
change game files, or add an autostart/background capture process.

Run `python -m tools.build_personal_package` from a clean, committed checkout
to stage the current build. The installer checks helper and asset hashes,
creates an immutable named source snapshot, runs its `--check` startup, and
then writes the Desktop launchers. The Desktop `Mithril Voices.cmd` starts the
current version after the same code/runtime/asset checks. The `Mithril Voices`
Desktop folder contains **Check Mithril Voices.cmd**, a README, installation
metadata, and **Mithril Voices (previous).cmd**. The previous launcher points
to a separate snapshot of the owner-tested manual flow at
`790bf46947dc0f2ebc3336f8ec20f8d48dcc36d7`; it is a rollback path if
the new package fails. Both snapshots depend on the existing task environment
remaining at its current location.

The startup check verifies all packaged source hashes, Python 3.12 x64, Qt
and voice runtime versions, the pinned Windows capture/OCR helpers, and the
local model/config/Emma/Fable hashes. Tesseract is optional because Windows
OCR is primary. It opens no game window and no audio device. A failed check
stops before the window picker and gives a reason code with a next step.
The package build ID and status codes go to a bounded private log under that
snapshot's `.audition/logs`; no window title, image, OCR text, speech text or
process path goes into the log. User preferences are an atomic private JSON
file under `.audition/preferences.json`: stable voice ID, exact speaker ID and
description, and the opt-in cache switch. They contain no quest text. A
missing or changed speaker is never silently replaced by another output.

The voice-provider seam maps stable IDs to explicitly registered renderers.
Only the installed offline Kokoro renderer is registered now. A future local
or cloud provider would need a separate approval, rights and privacy review,
its own bounded child renderer, an approved voice catalog, and a complete-WAV
identity. The manual review and explicit Read gate stay upstream of providers.

The package still requires a fresh, explicit LOTRO window selection and one
capture per launch. Review/edit and confirmation precede each Read. Stop and
new-crop actions revoke the current audio generation. No automatic narration
is enabled. The owner has already reported Stop/replay, another quest without
old text, and a voice change working in the prior manual version; this package
still needs one owner-run audible check after installation. Model/audio/corpus
rights and full product acceptance remain separate qualification gates.
