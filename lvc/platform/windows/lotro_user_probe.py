"""Manual one-frame LOTRO window Preview with an explicit user crop and no saved pixels."""
# pyright: reportMissingImports=false
from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import struct
import subprocess
import sys
import tkinter as tk
import unicodedata
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, ImageTk

from lvc.vision.binding import PixelRect
from lvc.vision.text_gate import OcrPass, OcrWord, decide_text

TASK_ROOT = Path(__file__).resolve().parents[4]
NATIVE_PROBE = TASK_ROOT / "test-tmp" / "lotro_frame_probe.exe"
TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
EXPECTED_NATIVE_SHA256 = "3e64737ea1feb5805e5f8430546b7c4d4566a6b40b97635502fad90db277d9ba"
MAX_PIXELS = 32_000_000
MAX_FRAME_BYTES = 12 + MAX_PIXELS * 3

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                                   wintypes.LPARAM), wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
kernel32.GetProcessTimes.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


@dataclass(frozen=True)
class Candidate:
    hwnd: int
    pid: int
    process_started_ticks: int
    executable_path: str
    title: str
    client_width: int
    client_height: int


def approved_executable(path: str) -> bool:
    return Path(path).name.casefold() == "lotroclient64.exe"


def filetime_ticks(value: wintypes.FILETIME) -> int:
    return value.dwLowDateTime | value.dwHighDateTime << 32


def candidate_for_hwnd(hwnd: int) -> Candidate | None:
    if (not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd)
            or user32.GetAncestor(hwnd, 2) != hwnd):
        return None
    client = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        return None
    width, height = client.right - client.left, client.bottom - client.top
    if width <= 0 or height <= 0:
        return None
    pid = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
        return None
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return None
    try:
        created, exited, cpu_kernel, cpu_user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(cpu_kernel), ctypes.byref(cpu_user)):
            return None
        path_buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path_buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, path_buffer,
                                                    ctypes.byref(length)):
            return None
        path = path_buffer.value
    finally:
        kernel32.CloseHandle(handle)
    if not approved_executable(path):
        return None
    title_buffer = ctypes.create_unicode_buffer(min(user32.GetWindowTextLengthW(hwnd) + 1, 512))
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
    return Candidate(hwnd, pid.value, filetime_ticks(created), path,
                     title_buffer.value, width, height)


def eligible_windows() -> list[Candidate]:
    found: list[Candidate] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd: int, _context: int) -> bool:
        candidate = candidate_for_hwnd(hwnd)
        if candidate is not None:
            found.append(candidate)
        return True

    if not user32.EnumWindows(visit, 0):
        raise OSError("Window enumeration failed")
    return found


def native_command(candidate: Candidate) -> list[str]:
    if not approved_executable(candidate.executable_path):
        raise ValueError("Selected process is not the approved retail 64-bit client")
    return [str(NATIVE_PROBE), "--explicit-lotro-window", str(candidate.hwnd),
            str(candidate.pid), str(candidate.process_started_ticks),
            candidate.executable_path]


def decode_frame(data: bytes) -> Image.Image:
    if len(data) < 12 or data[:4] != b"LVCF":
        raise ValueError("Native capture did not return a frame")
    width, height = struct.unpack_from("<II", data, 4)
    if not width or not height or width * height > MAX_PIXELS:
        raise ValueError("Native frame dimensions are invalid")
    if len(data) != 12 + width * height * 3:
        raise ValueError("Native frame length is invalid")
    return Image.frombytes("RGB", (width, height), data[12:])


def display_crop_to_frame(x1: float, y1: float, x2: float, y2: float,
                          scale: float, width: int, height: int) -> PixelRect | None:
    if scale <= 0:
        return None
    left = max(0, min(width, round(min(x1, x2) / scale)))
    top = max(0, min(height, round(min(y1, y2) / scale)))
    right = max(0, min(width, round(max(x1, x2) / scale)))
    bottom = max(0, min(height, round(max(y1, y2) / scale)))
    rect = PixelRect(left, top, right - left, bottom - top)
    return rect if rect.width >= 20 and rect.height >= 20 and rect.inside(width, height) else None


def choose_crop(image: Image.Image) -> PixelRect | None:
    """Show only the selected-window frame locally; return the user's body crop."""
    root = tk.Tk()
    root.title("Mithril Voices: select visible quest body only")
    scale = min(1.0, 1200 / image.width, 800 / image.height)
    shown = image.resize((round(image.width * scale), round(image.height * scale)))
    photo = ImageTk.PhotoImage(shown, master=root)
    canvas = tk.Canvas(root, width=shown.width, height=shown.height, cursor="crosshair")
    canvas.pack()
    canvas.create_image(0, 0, image=photo, anchor="nw")
    tk.Label(root, text="Drag around visible quest BODY text only. Exclude title, rewards, buttons, chat and clipped lines.").pack()
    selection: dict[str, float] = {}
    answer: list[PixelRect | None] = [None]

    def press(event: tk.Event) -> None:
        selection.update(x1=event.x, y1=event.y, x2=event.x, y2=event.y)

    def drag(event: tk.Event) -> None:
        if "x1" not in selection:
            return
        selection.update(x2=event.x, y2=event.y)
        canvas.delete("selection")
        canvas.create_rectangle(selection["x1"], selection["y1"], event.x, event.y,
                                outline="red", width=2, tags="selection")

    def confirm() -> None:
        if len(selection) != 4:
            return
        answer[0] = display_crop_to_frame(selection["x1"], selection["y1"],
                                          selection["x2"], selection["y2"],
                                          scale, image.width, image.height)
        if answer[0] is not None:
            root.destroy()

    canvas.bind("<Button-1>", press)
    canvas.bind("<B1-Motion>", drag)
    tk.Button(root, text="Preview OCR of selected crop", command=confirm).pack()
    tk.Button(root, text="Cancel without OCR", command=root.destroy).pack()
    root.mainloop()
    return answer[0]


def recognize(image: Image.Image, *, alternative: bool) -> OcrPass:
    gray = ImageOps.grayscale(image)
    processed = ImageOps.autocontrast(gray).resize((gray.width * 2, gray.height * 2)) if alternative else gray
    encoded = io.BytesIO()
    processed.save(encoded, format="PNG")
    completed = subprocess.run([str(TESSERACT), "stdin", "stdout", "-l", "eng",
                                "--psm", "6", "tsv"], input=encoded.getvalue(),
                               capture_output=True, timeout=10, check=False)
    if completed.returncode != 0:
        raise RuntimeError("Local Tesseract OCR failed")
    rows = csv.DictReader(io.StringIO(completed.stdout.decode("utf-8-sig")),
                          delimiter="\t")
    words: list[OcrWord] = []
    lines: list[str] = []
    current_line: tuple[int, int, int] | None = None
    line_words: list[str] = []
    margin = 6 if alternative else 3
    for row in rows:
        value = row["text"]
        text = unicodedata.normalize("NFC", value.strip())
        score = float(row["conf"])
        if not text or score < 0:
            continue
        key = (int(row["block_num"]), int(row["par_num"]),
               int(row["line_num"]))
        if current_line is not None and key != current_line:
            lines.append(" ".join(line_words))
            line_words = []
        current_line = key
        line_words.append(text)
        x, y = int(row["left"]), int(row["top"])
        right = x + int(row["width"])
        bottom = y + int(row["height"])
        clipped = (x <= margin or y <= margin or right >= processed.width - margin
                   or bottom >= processed.height - margin)
        words.append(OcrWord(text, score, clipped))
    if line_words:
        lines.append(" ".join(line_words))
    return OcrPass("\n".join(lines), tuple(words))


def main() -> int:
    if sys.platform != "win32":
        raise RuntimeError("This probe is Windows-only")
    if not NATIVE_PROBE.is_file() or not TESSERACT.is_file():
        raise RuntimeError("Prepared native probe or existing local Tesseract is missing")
    actual_hash = hashlib.sha256(NATIVE_PROBE.read_bytes()).hexdigest()
    if actual_hash != EXPECTED_NATIVE_SHA256:
        raise RuntimeError("Native probe hash differs from the reviewed local build")
    candidates = eligible_windows()
    if not candidates:
        print("No visible retail 64-bit LOTRO window with verifiable process identity was found.")
        return 2
    print("Verified LOTRO candidates (metadata only; no capture yet):")
    for index, candidate in enumerate(candidates, 1):
        print(f"{index}. PID {candidate.pid}, client {candidate.client_width}x{candidate.client_height}, "
              f"title {candidate.title!r}, executable {candidate.executable_path}")
    selected = input("Select candidate number, or press Enter to cancel: ").strip()
    if not selected.isascii() or not selected.isdecimal() or not 1 <= int(selected) <= len(candidates):
        print("Canceled before capture.")
        return 0
    candidate = candidates[int(selected) - 1]
    approval = input(f"Type CAPTURE {selected} to allow one in-memory frame of this exact window: ").strip()
    if approval != f"CAPTURE {selected}":
        print("Canceled before capture.")
        return 0
    print("Return to the selected LOTRO window within 8 seconds. The probe captures one frame only.", flush=True)
    completed = subprocess.run(native_command(candidate), capture_output=True,
                               timeout=15, check=False)
    if completed.returncode != 0:
        reason = completed.stderr.decode("ascii", "replace").strip()[:160]
        print(f"Capture blocked: {reason or 'native probe failed'}")
        return 2
    if len(completed.stdout) > MAX_FRAME_BYTES:
        raise ValueError("Native frame exceeded the bounded pipe size")
    frame = decode_frame(completed.stdout)
    crop = choose_crop(frame)
    if crop is None:
        print("Canceled; no OCR was run.")
        return 0
    body = frame.crop((crop.x, crop.y, crop.x + crop.width, crop.y + crop.height))
    first = recognize(body, alternative=False)
    second = recognize(body, alternative=True)
    decision = decide_text(first, second, qualified_region=True)
    print("\nRaw local OCR Preview (not saved or uploaded):\n")
    print(decision.raw_text)
    print(f"\nTwo-pass gate: {decision.reason}; accepted={decision.accepted_text is not None}.")
    print(f"Crop: x={crop.x}, y={crop.y}, width={crop.width}, height={crop.height}; "
          f"frame={frame.width}x{frame.height}.")
    print("No speech was played and no image or OCR text was saved by this probe.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Probe stopped safely: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
