# WP-05 selected-window preparation, local only

This packet does not open a window or capture the screen. It adds a pure
fail-closed gate for a future explicitly selected window. Its identity includes
native handle, process ID, process creation time and executable path. A frame
is eligible only when the selection ticket, current verified window, capture
source identity, freshness sequence, geometry epoch and bounded crop agree.
Focus loss, minimize, window replacement and geometry change suspend the
binding. A newly verified frame after revalidation is required. Window title
alone has no authority. The crop is expressed in physical capture pixels;
no DPI-to-game-scale transform is guessed.

The text gate preserves raw first-pass text for Preview. Automatic acceptance
requires a qualified crop, complete words, two agreeing NFC/casefolded word
passes, all nonpunctuation word scores at least 40, and median at least 85.
It abstains on clipped words, low confidence, disagreement, empty output or
unqualified geometry. No OCR engine or screenshot is wired to live playback.
The pipeline accepts a bounded grayscale frame only after the identity gate,
extracts exactly the approved body crop, and then invokes an injected
recognizer. Rejected identities, stale frames, invalid crops and malformed
pixel buffers make zero OCR calls; a recognizer failure suspends live work.

The installed PySide6 6.12 `QCapturableWindow` exposes only `description`,
`isValid` and `swap` as public members. The local API capability probe did
not enumerate windows or capture a frame. It found no public native identity
accessor, so the proposed Qt `QWindowCapture` adapter cannot yet prove that
its selected object maps to the exact verified Windows handle. The adapter
remains disabled. The local receipt is
`../wp05-qt-window-identity-capability.json`.

A scoped alternative for the next packet is Windows Graphics Capture from an
explicitly verified HWND using the documented
[`IGraphicsCaptureItemInterop::CreateForWindow`](https://learn.microsoft.com/en-us/windows/win32/api/windows.graphics.capture.interop/nf-windows-graphics-capture-interop-igraphicscaptureiteminterop-createforwindow)
API. Verify the HWND's PID, process creation time, executable path, geometry
and visibility before capture and throughout the session; fail closed on
replacement or capture errors. Limit acquisition to the selected window and
the user's approved quest-region crop. Do not enable monitor or desktop-wide
capture, title-only matching, automatic fallback or raw-frame persistence.
The binding between returned frames and that HWND still needs a real adapter
test before this proposal becomes an implementation claim.

An additional local C++/WinRT probe was compiled with the already installed
Visual Studio Build Tools and Windows SDK. Its only possible target is a
window created by that probe process with original fixture text; it takes no
HWND argument. It checks native process ID, process creation time and
executable path before any capture call. A second same-title probe window,
an altered process-creation identity, a minimized window, a destroyed window
and an out-of-bounds crop were rejected. Actual OS handle reuse was not
forced; the altered creation time is a stale-identity simulation.
The interop setup follows Microsoft's
[MIT-licensed Win32 sample](https://github.com/microsoft/Windows.UI.Composition-Win32-Samples/tree/master/cpp/ScreenCaptureforHWND).

The probe stopped at `GraphicsCaptureSession::IsSupported()` with HRESULT
`0x80070005` (`E_ACCESSDENIED`) in this execution environment. It did not
call `CreateForWindow`, start a capture session, receive a frame, or save an
image. The native source is `lvc/platform/windows/owned_capture_probe.cpp`;
the final local receipt is `../wp05-owned-hwnd-capture-final.json`. This is
a **BLOCKED** capability probe, not a passed Windows Graphics Capture test.
It is not wired into the application. A separate execution context that
allows this exact application-owned WGC support check would be needed before
continuing live capture qualification. No capture/security permission was
changed here.

Synthetic tests cover duplicate-title/reused-handle rejection, unknown frame
source, stale tickets/frames, focus and geometry invalidation, crop bounds,
zero-OCR-call rejection, preservation-first OCR, clipped lines, confidence
and protected-number disagreement. The local pure QA lane collected 27 tests,
all passing. Separately, the installed local Tesseract 5.5.0 with `eng`
recognized an original in-memory phrase in two fixed passes and the text gate
accepted it. The phrase was generated in memory; no image was saved or screen
captured. Receipt: `../wp05-synthetic-ocr.json`. This does not qualify game OCR,
UI scaling, detector profiles, Tesseract packaging or rights. No real quest
panel test is ready until exact-window capture can supply verified frame
provenance and bounded crop metadata. WP-05, G1 and G2 remain incomplete.
