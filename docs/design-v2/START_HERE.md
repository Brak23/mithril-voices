# Start here

## What to provide the coding agent

Use the full ZIP contents, not only the DOCX. The Markdown specification is the reading authority; adjacent JSON contracts and test/work catalogs are normative. The DOCX is a human reading copy. This is a requirements handoff, not a working app or a pre-created GitHub fork.

Place the extracted handoff beside the intended workspace first. The agent must inspect any existing project before copying files over it. When adopting into the fork, preserve existing files, compare collisions, and keep original upstream notices/history. Do not overwrite an existing AGENTS.md without reconciling its authorized project instructions.

## Adoption prompt

```text
Adopt the attached LOTRO Voice Companion AI Implementation Contract v2.0
and its complete handoff package as the governing requirements.

Start with WP-00. Inspect the existing workspace, repository, permissions,
source, tests, artifacts, and any prior implementation before changing
application code. Use the pinned Khazad base specified in the contract.
Preserve working user changes and valid reusable integrations.

Perform the bounded source audit and local bootstrap. Implement and test
a guarded idempotent bootstrap script before using its write operations.
Do not execute the inline command recipe as an unchecked script.

Check whether public-fork creation, GitHub owner/destination and pushing
have actually been approved. Do not infer them from this adoption prompt.
Proceed with authorized local work while missing remote permission blocks
only the remote action. Ask only for a genuinely blocking missing input.

Then execute dependency-ready packets in planning/tasks.json. Write all
required application and test code, using independent expected outcomes
from planning/acceptance-tests.json. Keep core, worker, audio and privacy
invariants. Do not replace requirements with your preferred architecture.

Run applicable checks and preserve real evidence. Tests needing Windows,
LOTRO, an audio endpoint or a GPU are not passed by mocks or generated code.
Record precise blockers and continue unrelated authorized implementation.
Do not publish, upload gameplay data, install a Lua plugin, buy assets, or
change security settings without the permission required by the contract.

Return the completed packet IDs, source/diff summary, actual test results,
failed/blocked gates, and the next dependency-ready action. Never report
flawless or complete based only on a demo or green shallow unit tests.
```

## Package check

Run `python verification/validate_handoff.py` in the extracted directory. Python 3.10+ and the development-only `jsonschema` package are needed for that check. It does not install dependencies automatically. Missing jsonschema is a blocked package-schema check, not permission to skip validation. WP-01 freezes actual development/runtime versions after clean Windows verification.

## Execution status on delivery

All application acceptance cases are NOT_RUN. All work packets are NOT_STARTED. No fork, push, application implementation, model download, GPU benchmark or live-game test was performed to create these documents. verification/handoff-validation.json, when present, refers only to the supplied requirements package.
