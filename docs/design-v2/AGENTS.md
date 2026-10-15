# LOTRO Voice Companion: agent contract

Read IMPLEMENTATION_SPEC.md v2.0 before modifying application behavior. It supersedes the earlier WPF/.NET design and chat proposals. Follow normative contracts in contracts/. Conflicts require a recorded spec decision, not guessed behavior.

Start with WP-00 in planning/tasks.json. Inspect the designated repository and pin the specified Khazad commit. Preserve dirty work, upstream history and notices. Do not run upstream installers/notebooks merely to audit source. Keep a source/reuse/rights map.

Use Python/PySide6, a pure deterministic core, isolated vision/TTS processes and one audio owner. No C# rewrite, runtime LLM, gameplay automation, unbounded queues or silent text repair. Stop must fence stale work at final audio admission.

Implement one packet per branch/worktree. Write failing desired-behavior tests with independent oracles, then the smallest change. Review scope and run relevant checks. Never remove a gate or change a test expectation just to get green.

Package-only check: python verification/validate_handoff.py
Application QA after WP-01 implements it: python tools/qa.py --suite quick
Other required suites: contract, replay, windows, gpu, package, release.

Read planning/permissions.json and actual owner instructions before remote writes, public forks, uploads, paid actions, Lua installation or publishing. A public upstream fork is public. Do not push upstream. Safe local work can continue while a narrower external gate is blocked.

Reports must include SHA, commands, exit codes, environment, fixture/artifact hashes and actual results. Missing Windows/GPU/game access is BLOCKED, not PASSED. Package consistency is not application verification. Never claim a generated test was run or label the product flawless.

Finish the selected packet, record exact remaining blockers, and continue dependency-ready authorized work. No background promises and no broad re-planning beyond the contract.
