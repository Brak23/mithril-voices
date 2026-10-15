"""Inspect installed Qt capture identity API without enumerating or capturing windows."""
# pyright: reportMissingImports=false
from __future__ import annotations

import json

from PySide6 import __version__ as pyside_version
from PySide6.QtMultimedia import QCapturableWindow, QWindowCapture


def main() -> int:
    public = sorted(name for name in dir(QCapturableWindow) if not name.startswith("_"))
    native_identity_accessors = {"winId", "handle", "nativeHandle", "id", "processId"}
    result = {
        "scope": "INSTALLED_QT_API_SURFACE_ONLY",
        "pyside_version": pyside_version,
        "qcapturable_window_public_members": public,
        "qwindow_capture_available": QWindowCapture is not None,
        "public_native_identity_accessor": bool(native_identity_accessors.intersection(public)),
        "window_enumerated": False,
        "screen_captured": False,
        "conclusion": ("NATIVE_ACCESSOR_REQUIRES_VALIDATION"
                       if native_identity_accessors.intersection(public)
                       else "BLOCKED_NATIVE_IDENTITY_MAPPING_WITH_PUBLIC_QT_API"),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
