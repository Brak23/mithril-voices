# Qualified observation to reducer bridge (WP-08 slice)

`lvc/vision/auto_core_adapter.py` connects the pure automatic observation
policy to the existing v2 reducer. It accepts a caller-supplied qualified
selected-window observation, waits for the policy's stable page token, creates
the corresponding core page reservation, and passes only the current OCR
validation to `ValidatedText`. Its result carries the reducer's effects and,
only when a `synthesize` effect exists, the accepted text for a future host to
send to a supervised speech worker. A page change, panel close, Stop, Auto Off,
or detector suspension revokes pending validation and returns fence/cancel
effects for the host to execute.

`profile_qualified` defaults to false. The current LOTRO calibration profile
is diagnostic and does not meet that gate. The observation UI and Desktop
launcher do not import or activate this bridge. The bridge itself performs no
window capture, OCR, synthesis, or playback. The future host must provide
qualified detector evidence, checked text, worker supervision, and renderer
generation fencing before these effects can authorize audible speech.

Windows verification on the implementation branch: five new synthetic bridge
tests passed; the full `tests/v2` suite passed (241 tests) using a workspace
temporary directory because this sandbox's default pytest temp path was
unavailable. Ruff and Pyright passed on the new module and tests. These are
synthetic control results, not live LOTRO, device, or G3 qualification.
