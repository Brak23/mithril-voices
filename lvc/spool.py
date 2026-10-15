"""Windows host-side validation for a complete synthetic PCM WAV spool unit.

The caller creates a private session directory and runs this blocking I/O on a
preparation worker, never on the GUI or audio thread. No file path is given to
the sink; the returned PCM is a bounded in-memory copy of one verified handle.
"""
from __future__ import annotations

import ctypes
import hashlib
import hmac
import io
import ntpath
import os
import struct
import sys
import wave
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from lvc.core import RequestToken
from lvc.synthetic_flow import AcceptedUnit, StaleArtifact

RATE = 48_000
CHANNELS = 1
SAMPLE_WIDTH = 2
MAX_UNIT_BYTES = 16 * 1024 * 1024
MAX_UNIT_FRAMES = 30 * RATE
MAX_ADMITTED_UNITS = 2
MAX_ADMITTED_BYTES = 32 * 1024 * 1024
MAX_ADMITTED_FRAMES = 60 * RATE

GENERIC_READ = 0x80000000
FILE_READ_ATTRIBUTES = 0x80
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
FILE_SHARE_DELETE = 0x4
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class InvalidSpool(ValueError):
    """Rejected audio or path, without echoing local paths or content."""


@dataclass(frozen=True)
class AdmittedUsage:
    byte_count: int
    frame_count: int


class ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("created", wintypes.FILETIME),
        ("accessed", wintypes.FILETIME),
        ("modified", wintypes.FILETIME),
        ("volume_serial", wintypes.DWORD),
        ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD),
        ("link_count", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]

    @property
    def size(self) -> int:
        return (self.size_high << 32) | self.size_low


def _api() -> Any:
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.GetFileInformationByHandle.argtypes = [wintypes.HANDLE,
                                               ctypes.POINTER(ByHandleFileInformation)]
    api.GetFileInformationByHandle.restype = wintypes.BOOL
    api.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                              wintypes.DWORD, wintypes.DWORD]
    api.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    return api


def _open(api: Any, path: Path, *, directory: bool) -> int:
    rights = FILE_READ_ATTRIBUTES if directory else GENERIC_READ
    sharing = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE if directory else FILE_SHARE_READ
    flags = FILE_FLAG_OPEN_REPARSE_POINT | (FILE_FLAG_BACKUP_SEMANTICS if directory else 0)
    handle = api.CreateFileW(str(path), rights, sharing, None, OPEN_EXISTING, flags, None)
    if not handle or int(handle) == ctypes.c_void_p(-1).value:
        raise InvalidSpool("Spool object could not be opened")
    return int(handle)


def _info(api: Any, handle: int) -> ByHandleFileInformation:
    info = ByHandleFileInformation()
    if not api.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise InvalidSpool("Spool handle metadata unavailable")
    return info


def _checked_info(api: Any, handle: int) -> ByHandleFileInformation:
    info = _info(api, handle)
    if info.attributes & FILE_ATTRIBUTE_REPARSE_POINT or info.link_count != 1:
        raise InvalidSpool("Reparse point or multiply linked spool object rejected")
    return info


def _final_path(api: Any, handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(32768)
    length = api.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if length == 0 or length >= len(buffer):
        raise InvalidSpool("Final spool handle path unavailable")
    return ntpath.normcase(ntpath.normpath(buffer.value))


def _read_owned_file(path: Path, root: Path, declared_bytes: int) -> bytes:
    if sys.platform != "win32":
        raise InvalidSpool("Windows handle validation required")
    import msvcrt  # Windows-only CRT handle transfer.

    api = _api()
    root_handle = _open(api, root, directory=True)
    try:
        root_info = _checked_info(api, root_handle)
        if not root_info.attributes & FILE_ATTRIBUTE_DIRECTORY:
            raise InvalidSpool("Spool root is not a directory")
        root_final = _final_path(api, root_handle)
        file_handle = _open(api, path, directory=False)
        try:
            file_info = _checked_info(api, file_handle)
            if file_info.attributes & FILE_ATTRIBUTE_DIRECTORY:
                raise InvalidSpool("Spool unit is not a regular file")
            if ntpath.dirname(_final_path(api, file_handle)) != root_final:
                raise InvalidSpool("Spool unit handle is outside the owned directory")
            if file_info.size != declared_bytes:
                raise InvalidSpool("Declared WAV byte count differs from opened file")
            # CRT owns this exact checked handle from here; no path is reopened.
            fd = msvcrt.open_osfhandle(file_handle, os.O_RDONLY | os.O_BINARY)
            file_handle = 0
            with os.fdopen(fd, "rb") as stream:
                raw = stream.read(declared_bytes + 1)
                if len(raw) != declared_bytes or os.fstat(stream.fileno()).st_size != declared_bytes:
                    raise InvalidSpool("Spool file changed during bounded read")
            return raw
        finally:
            if file_handle:
                api.CloseHandle(file_handle)
    finally:
        api.CloseHandle(root_handle)


def _decode_pcm(raw: bytes, declared_frames: int) -> bytes:
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise InvalidSpool("Malformed WAV container")
    if struct.unpack_from("<I", raw, 4)[0] != len(raw) - 8:
        raise InvalidSpool("RIFF length differs from actual file")
    try:
        with wave.open(io.BytesIO(raw), "rb") as source:
            if (source.getnchannels() != CHANNELS or source.getsampwidth() != SAMPLE_WIDTH
                    or source.getframerate() != RATE or source.getcomptype() != "NONE"
                    or source.getnframes() != declared_frames):
                raise InvalidSpool("WAV format or frame count invalid")
            pcm = source.readframes(declared_frames + 1)
    except (wave.Error, EOFError, OSError, struct.error) as exc:
        raise InvalidSpool("WAV structure invalid") from exc
    if len(pcm) != declared_frames * SAMPLE_WIDTH:
        raise InvalidSpool("WAV sample payload truncated or oversized")
    # Signed 16-bit PCM represents finite samples by construction; float/NaN
    # formats have been excluded above.
    return pcm


class SpoolValidator:
    def __init__(self, root: Path, session_id: UUID, unit_id: UUID,
                 owner_root: Path,
                 admitted: tuple[AdmittedUsage, ...] = ()):
        if (not root.is_absolute() or not owner_root.is_absolute()
                or root.name != str(session_id)
                or ntpath.normcase(ntpath.normpath(str(root.parent)))
                != ntpath.normcase(ntpath.normpath(str(owner_root)))):
            raise InvalidSpool("Spool root must be the owned absolute session directory")
        self.root = root
        self.session_id = session_id
        self.unit_id = unit_id
        if any(type(item.byte_count) is not int or type(item.frame_count) is not int
               or not 0 <= item.byte_count <= MAX_UNIT_BYTES
               or not 0 <= item.frame_count <= MAX_UNIT_FRAMES for item in admitted):
            raise InvalidSpool("Invalid admitted-unit budget record")
        self.admitted = admitted

    def __call__(self, token: RequestToken, result: dict[str, Any], speech_text: str,
                 current: Callable[[], bool]) -> AcceptedUnit:
        if token.session_id != self.session_id or not current():
            raise StaleArtifact("Spool request is no longer current")
        expected_name = f"{token.request_id}.wav"
        if result.get("filename") != expected_name or result.get("unit_id") != str(self.unit_id):
            raise InvalidSpool("Spool file or unit ID differs from host request")
        if (result.get("kind") != "audio" or result.get("sample_rate") != RATE
                or result.get("channels") != CHANNELS or result.get("sample_format") != "s16le"):
            raise InvalidSpool("PCM descriptor format invalid")
        byte_count, frame_count = result.get("bytes"), result.get("frame_count")
        if (type(byte_count) is not int or type(frame_count) is not int
                or not 44 <= byte_count <= MAX_UNIT_BYTES
                or not 1 <= frame_count <= MAX_UNIT_FRAMES
                or byte_count < 44 + frame_count * SAMPLE_WIDTH):
            raise InvalidSpool("Unit size or duration exceeds the pre-read limit")
        if (len(self.admitted) >= MAX_ADMITTED_UNITS
                or sum(item.byte_count for item in self.admitted) + byte_count > MAX_ADMITTED_BYTES
                or sum(item.frame_count for item in self.admitted) + frame_count > MAX_ADMITTED_FRAMES):
            raise InvalidSpool("Cumulative spool admission budget exceeded")
        digest = result.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise InvalidSpool("Invalid declared WAV digest")
        raw = _read_owned_file(self.root / expected_name, self.root, byte_count)
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), digest):
            raise InvalidSpool("WAV hash differs from opened file")
        pcm = _decode_pcm(raw, frame_count)
        if speech_text.strip() and not any(pcm):
            raise InvalidSpool("Silent clip for nonempty speech")
        if not current():
            raise StaleArtifact("Spool request changed during validation")
        return AcceptedUnit(digest, str(self.unit_id), frame_count, pcm)
