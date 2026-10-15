"""Explicit local Kokoro audition prerequisites; never imports or runs a model."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuditionArtifact:
    role: str
    path: Path
    sha256: str
    source_url: str
    license_evidence: str
    approved_for_local_use: bool

    def inspect(self) -> str:
        if (not self.approved_for_local_use or not self.source_url
                or not self.license_evidence):
            return "APPROVAL_OR_RIGHTS_MISSING"
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            return "PIN_MISSING"
        if not self.path.is_file():
            return "FILE_MISSING"
        with self.path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return "VERIFIED" if digest == self.sha256 else "HASH_MISMATCH"


def audition_readiness(artifacts: tuple[AuditionArtifact, ...]) -> dict[str, str]:
    required = {"kokoro_weights", "voice_weights", "runtime_lock", "pronunciation_data"}
    roles = [artifact.role for artifact in artifacts]
    if len(roles) != len(set(roles)):
        raise ValueError("Duplicate audition artifact role")
    return {role: next((artifact.inspect() for artifact in artifacts
                        if artifact.role == role), "MISSING_MANIFEST_ENTRY")
            for role in sorted(required)}
