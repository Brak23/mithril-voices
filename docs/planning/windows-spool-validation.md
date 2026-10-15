# WP-03 generated WAV spool validation

This local branch adds `lvc.spool.SpoolValidator` to the existing single-unit
synthetic controller flow. The contained QProcess fixture writes five original
PCM samples to `<request_uuid>.part`, closes the file, atomically renames it to
`<request_uuid>.wav`, and sends its measured descriptor. The host validator
opens that exact file with a Windows handle, requires the session directory to
be a direct child of the host-designated owner root, checks that directory
and final handle path, rejects reparse points and multiple links, and reads
from the checked handle. It enforces the declared byte count and SHA-256, RIFF
length, mono 48,000 Hz signed 16-bit PCM, actual frame count, non-silence for
nonempty speech, the 16 MiB/30-second unit caps, and the 32 MiB/60-second/
two-unit cumulative admission limits before reading. Since the only decoded
format is signed 16-bit PCM, its samples are finite by construction; float WAV
and NaN payloads are rejected.

The validator checks current request/generation before and after the bounded
read. The controller also rechecks before admission, so Stop during validation
cannot prepare or write a stale unit. The success probe records a verified
10-byte PCM copy and one fake sink write. It does **not** open QAudioSink or
claim that the human heard audio. Generated files are created under the task's
isolated temporary directory and removed after the probe. The
[QA report](../evidence/wp03/windows-spool-validation.json) includes direct
negative tests and the existing flow/QProcess regression. The
[success result](../evidence/wp03/windows-spool-success.json) records the
verified byte count and owned process cleanup.

Windows tests used real file and directory symlinks. This host denied a test
hardlink creation; the multiply linked metadata rejection branch was exercised
by injection. Path ownership still depends on the future host creating a
private session directory under its selected known-folder root. A production
spool manager must maintain cumulative admitted-unit claims and supervise the
additional in-progress `.part` size and deadline. The QProcess startup barrier
is still fixture-specific; manifests, runtime identity, and a reusable worker
adapter are not qualified. WP-03, WP-04 and G1 remain incomplete.

The next prerequisite for **real audio readiness** is a single Qt audio owner
that consumes only validated in-memory PCM, acknowledges generation fences,
resets the sink on Stop, and measures physical endpoint latency. Before that
can be safely connected to an actual model worker, the reusable supervised
launch/manifest path and `.part` size/deadline enforcement also remain required.
This batch used no LOTRO, model download, external audio device, or game files.

The handle checks follow Microsoft's [CreateFileW reparse-point behavior](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
[file-handle metadata](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle),
and [final handle path](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)
documentation.
