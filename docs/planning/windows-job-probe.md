# Windows WP-03 process-tree probe

This branch stacks locally on the cancellation safeguards branch. The probe
uses one original, finite-life Python parent and one descendant created by
that parent. The parent waits for a command before creating its descendant, so
the probe assigns it to a fresh unnamed Windows Job Object first. It checks
membership for both processes. The child then acknowledges cancel but remains
running; after a measured 1,000 ms, the probe either calls
`TerminateJobObject` or closes the last job handle with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. In both modes it waits for the exact
parent and descendant process handles to become signaled. It never searches
for or kills other process names or game processes.

On BryceGamingPC, both modes passed. The parent was already in an inherited
job before assignment; nested assignment to the new job succeeded for this
controlled child. Reports are
[`windows-job-terminate.json`](../evidence/wp03/windows-job-terminate.json) and
[`windows-job-close.json`](../evidence/wp03/windows-job-close.json). They record
the development tree as dirty and are followed by clean committed-SHA probes
outside the repository. The source hashes and platform are captured in each
report. No screenshots, game data, audio, model assets or personal paths are
included.

This is a Windows containment **probe**, not a production launcher. The real
worker must enter containment before it can create a descendant; the test's
stdin barrier does not itself establish that for arbitrary QProcess workers.
Other inherited job restrictions, failed assignment recovery, schema-validated
IPC, deadlines for actual workers, Qt event-loop responsiveness and a full
eight-hour soak remain open. Thus AT-047 has partial Windows evidence, while
WP-03 and G1 are incomplete. A failed containment probe for any selected
runtime must block activation of that runtime.

The probe follows Microsoft's documentation for
[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
[assignment](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject),
and [job termination](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject).

The branch remains local while the GitHub AI Scan billing state is unknown.
Before a push, the owner should open the verified public
[repository](https://github.com/Brak23/mithril-voices), enter Settings, and
read the AI Scan setting. They should also read their GitHub billing Usage and
Budgets views. No private settings page or billing balance was verifiable from
this task because the supported signed-in browser helper did not start.
