"""Pure identity and freshness gate for a future selected-window capture adapter."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from uuid import UUID


@dataclass(frozen=True)
class NativeWindowIdentity:
    handle: int
    process_id: int
    process_creation_ticks: int
    executable_path: str

    def __post_init__(self) -> None:
        if (self.handle <= 0 or self.process_id <= 0 or self.process_creation_ticks <= 0
                or not self.executable_path):
            raise ValueError("Incomplete native window identity")


@dataclass(frozen=True)
class WindowFacts:
    identity: NativeWindowIdentity
    native_verified: bool
    visible: bool
    minimized: bool
    focused: bool
    client_width: int
    client_height: int
    dpi: int

    @property
    def geometry(self) -> tuple[int, int, int]:
        return self.client_width, self.client_height, self.dpi

    @property
    def usable(self) -> bool:
        return (self.native_verified and self.visible and not self.minimized
                and self.focused and self.client_width > 0 and self.client_height > 0
                and self.dpi > 0)


@dataclass(frozen=True)
class PixelRect:
    x: int
    y: int
    width: int
    height: int

    def inside(self, frame_width: int, frame_height: int) -> bool:
        return (self.x >= 0 and self.y >= 0 and self.width > 0 and self.height > 0
                and self.x + self.width <= frame_width
                and self.y + self.height <= frame_height)


@dataclass(frozen=True)
class CaptureTicket:
    binding_id: UUID
    identity: NativeWindowIdentity
    geometry_epoch: int


@dataclass(frozen=True)
class FrameMetadata:
    source_identity: NativeWindowIdentity | None
    source_native_verified: bool
    capture_seq: int
    acquired_monotonic_ns: int
    width: int
    height: int


class FrameStatus(str, Enum):
    READY = "READY"
    SUSPENDED = "SUSPENDED"
    WRONG_WINDOW = "WRONG_WINDOW"
    SOURCE_UNVERIFIED = "SOURCE_UNVERIFIED"
    STALE_FRAME = "STALE_FRAME"
    GEOMETRY_INVALID = "GEOMETRY_INVALID"


@dataclass(frozen=True)
class SelectedWindow:
    identity: NativeWindowIdentity
    binding_id: UUID
    geometry: tuple[int, int, int]
    geometry_epoch: int
    selected_monotonic_ns: int
    last_capture_seq: int = -1
    suspended: bool = False

    @classmethod
    def select(cls, facts: WindowFacts, approved_executable_path: str,
               binding_id: UUID, now_ns: int) -> SelectedWindow:
        if (not facts.usable or facts.identity.executable_path != approved_executable_path
                or binding_id.int == 0 or now_ns < 0):
            raise ValueError("Window cannot be selected without verified native identity")
        return cls(facts.identity, binding_id, facts.geometry, 1, now_ns)

    def ticket(self) -> CaptureTicket | None:
        if self.suspended:
            return None
        return CaptureTicket(self.binding_id, self.identity, self.geometry_epoch)

    def suspend(self) -> SelectedWindow:
        if self.suspended:
            return self
        return replace(self, suspended=True, geometry_epoch=self.geometry_epoch + 1)

    def revalidate(self, facts: WindowFacts, now_ns: int) -> SelectedWindow:
        if (facts.identity != self.identity or not facts.usable
                or now_ns <= self.selected_monotonic_ns):
            raise ValueError("Selected native window is unavailable")
        return replace(self, geometry=facts.geometry, geometry_epoch=self.geometry_epoch + 1,
                       selected_monotonic_ns=now_ns, suspended=False)

    def accept(self, ticket: CaptureTicket, facts: WindowFacts, frame: FrameMetadata,
               crop: PixelRect | None) -> tuple[SelectedWindow, FrameStatus]:
        if self.suspended:
            return self, FrameStatus.SUSPENDED
        if (ticket.binding_id != self.binding_id or ticket.identity != self.identity
                or ticket.geometry_epoch != self.geometry_epoch):
            return self, FrameStatus.STALE_FRAME
        if facts.identity != self.identity:
            return self.suspend(), FrameStatus.WRONG_WINDOW
        if not facts.usable:
            return self.suspend(), FrameStatus.SUSPENDED
        if facts.geometry != self.geometry:
            return self.suspend(), FrameStatus.GEOMETRY_INVALID
        if not frame.source_native_verified or frame.source_identity is None:
            return self.suspend(), FrameStatus.SOURCE_UNVERIFIED
        if frame.source_identity != self.identity:
            return self.suspend(), FrameStatus.WRONG_WINDOW
        if (frame.capture_seq <= self.last_capture_seq
                or frame.acquired_monotonic_ns <= self.selected_monotonic_ns):
            return self, FrameStatus.STALE_FRAME
        if crop is None or not crop.inside(frame.width, frame.height):
            return self, FrameStatus.GEOMETRY_INVALID
        return replace(self, last_capture_seq=frame.capture_seq), FrameStatus.READY
