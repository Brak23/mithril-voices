# Windows WP-03 synthetic QProcess supervision slice

This branch stacks on the local Windows Job Object probe. A Qt `QProcess`
starts a fixed original Python fixture with separate stdin, stdout, and stderr.
The fixture waits for an `init` line before spawning one finite-life descendant.
After Qt reports startup, the host opens the exact new process handle, assigns
it to a fresh unnamed Job Object with kill-on-close, checks membership, and only
then sends `init`. A failed assignment kills the exact Qt child while it is
still waiting for `init`; it cannot spawn the descendant in that case.

The host checks every input against the v2 IPC schema plus UTF-8, duplicate-key,
nonfinite-number, line/buffer, sender, sequence, nonce, role, manifest, and
request correlation rules. It limits each stdout drain to 32 messages or 5 ms.
The cancellation ledger marks the logical outcome at Stop, records the worker's
acknowledgment separately, and keeps its physical slot occupied until the tree
exits. A stale terminal message cannot release the slot or prevent the 1,000 ms
Job Object escalation. Only the owned parent and its descendant are targeted.

Seven Windows fixture cases passed: start failure, injected containment failure,
readiness timeout (300 ms test override), malformed JSON, wrong sequence,
acknowledged cancel with a hung worker, and a late canceled terminal with a
still-running worker. Both cancellation cases observed acknowledgment within
250 ms and owned-tree termination at or after 1,000 ms. Parent and descendant
handles were signaled after containment cleanup where created. The
[QA report](../evidence/wp03/windows-qprocess-supervisor.json) includes the
inventory, source hashes, and JUnit results. The
[case report](../evidence/wp03/windows-qprocess-cases.json) records the seven
observed outcomes and cleanup signals. The prior Job Object termination
probe also passed again after its owned-handle adapter changed.

This is an integration **probe**, not the application supervisor. Its stdin
barrier makes assignment-before-descendant deterministic for this fixture;
an arbitrary future worker may run before assignment. The production adapter,
its launch barrier and assignment-failure policy, artifact validation, audio
release, capture, model rights, LOTRO behavior, all IPC edge cases, 120-second
readiness limit, and long-running soak remain unqualified. WP-03 and G1 are
incomplete; LOTRO was not launched and no game files or settings were changed.

Run the bounded Windows lane from the repository with the isolated Python
environment: `.venv\Scripts\python.exe tools\qa.py --suite qprocess-supervisor`.
The tests invoke the separately isolated `qt-dev-venv` PySide6 interpreter.
