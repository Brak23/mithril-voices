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
import unicodedata
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from lvc.platform.windows.lotro_probe_ui import Viewport, show_preview
from lvc.vision.binding import PixelRect
from lvc.vision.text_gate import OcrPass, OcrWord

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
    return Viewport(width, height, scale).crop(x1, y1, x2, y2)


TSV_HEADER = ("level", "page_num", "block_num", "par_num", "line_num",
              "word_num", "left", "top", "width", "height", "conf", "text")


def parse_tesseract_tsv(payload: bytes, *, width: int, height: int,
                        margin: int) -> OcrPass:
    """Parse Tesseract's literal tab records; OCR quotation marks are not CSV syntax."""
    try:
        source = io.StringIO(payload.decode("utf-8-sig"), newline="")
        rows = csv.reader(source, delimiter="\t", quoting=csv.QUOTE_NONE)
        if tuple(next(rows, ())) != TSV_HEADER:
            raise ValueError("OCR_TSV_HEADER_INVALID")
        words: list[OcrWord] = []
        lines: list[str] = []
        line_words: list[str] = []
        current_line: tuple[int, int, int, int] | None = None
        for row in rows:
            if not row:
                continue
            if len(row) != len(TSV_HEADER):
                raise ValueError("OCR_TSV_ROW_INVALID")
            level, page, block, para, line, word = (int(field) for field in row[:6])
            if not 1 <= level <= 5:
                raise ValueError("OCR_TSV_ROW_INVALID")
            if level != 5:
                continue  # Structural rows have conf=-1 and no word text.
            if word <= 0:
                raise ValueError("OCR_TSV_ROW_INVALID")
            x, y, word_width, word_height = (int(field) for field in row[6:10])
            score = float(row[10])
            text = unicodedata.normalize("NFC", row[11].strip())
            key = (page, block, para, line)
            if text:
                if current_line is not None and key != current_line:
                    lines.append(" ".join(line_words))
                    line_words = []
                current_line = key
                line_words.append(text)
            clipped = (x <= margin or y <= margin or word_width <= 0 or
                       word_height <= 0 or x + word_width >= width - margin or
                       y + word_height >= height - margin)
            # Retain invalid word rows in the gate input so they cannot be
            # silently omitted from an otherwise plausible Preview.
            words.append(OcrWord(text, score, clipped))
        if line_words:
            lines.append(" ".join(line_words))
        return OcrPass("\n".join(lines), tuple(words))
    except ValueError as exc:
        if str(exc).startswith("OCR_TSV_"):
            raise
        raise ValueError("OCR_TSV_ROW_INVALID") from exc
    except (UnicodeError, csv.Error, TypeError, OverflowError) as exc:
        raise ValueError("OCR_TSV_ROW_INVALID") from exc


def recognize(image: Image.Image, *, alternative: bool,
              runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None) -> OcrPass:
    gray = ImageOps.grayscale(image)
    processed = ImageOps.autocontrast(gray).resize((gray.width * 2, gray.height * 2)) if alternative else gray
    encoded = io.BytesIO()
    processed.save(encoded, format="PNG")
    run = runner if runner is not None else subprocess.run
    completed = run([str(TESSERACT), "stdin", "stdout", "-l", "eng",
                     "--psm", "6", "tsv"], input=encoded.getvalue(),
                    capture_output=True, timeout=10, check=False)
    if completed.returncode != 0:
        raise RuntimeError("Local Tesseract OCR failed")
    return parse_tesseract_tsv(completed.stdout, width=processed.width,
                               height=processed.height,
                               margin=6 if alternative else 3)


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
    show_preview(frame, recognize)
    print("Preview closed. No image or OCR text was saved by this probe.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Probe stopped safely: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
