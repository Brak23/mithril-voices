# Mithril Voices implementation plan

Status: requirements adoption and source-based planning complete for review.
Application implementation has not started. WP-00/G0 is PARTIAL, and G1-G4 are
NOT_RUN. This plan maps v2.0 to the existing fork; the detailed contracts and all
78 requirement definitions remain in [the specification](../design-v2/IMPLEMENTATION_SPEC.md).

## Fixed scope and architecture

Target Windows 11 x64, retail 64-bit LOTRO, English, windowed/borderless mode and
qualified stock quest surfaces. The Mac used for this audit does not establish
Windows, GPU, game or endpoint compatibility. Preserve legacy Linux/Echoes code
without certifying the new runtime there. The v2 scope supersedes the preliminary
audit's suggestion to defer that support decision.

Use Python 3.12, PySide6 Qt Widgets, a pure deterministic reducer and immutable
request context. The Qt host owns controls and coordination; a vision process
owns selected-window capture/detection/OCR; one selected speech process owns
Kokoro CPU or OmniVoice inference. A dedicated audio thread is the only QAudioSink
owner; a separate preparation/storage thread owns SQLite/cache I/O. No host ML
imports, C# host, runtime LLM, HTTP UI, binary audio pipe or gameplay automation.

Keep raw OCR, accepted display text, speech text and optional canonical text
separate. Read complete visible spans. Stop revokes old request authority at final
audio admission; it is independent of worker cancellation. Page identity includes
interaction/content evidence, so same-NPC changes are observable during playback.
There is no page backlog, automatic fallback voice, offscreen expansion or
two-second Stop tombstone expiry.

The base reader needs no Lua bridge, corpus, GPU or cloud. Corpus remains off and
is optional WP-17. Implementing the OmniVoice adapter/report is required; activating
its premium profile remains conditional. Actual model/voice IDs and exact dependency
versions must come from audited installed artifacts and clean Windows qualification.

## Requirements and evidence index

The adopted catalogs contain 78 requirements, 85 acceptance cases, 31 behavior
events and 18 work packets. These counts were independently checked. Every original
requirement maps to its test IDs and packet owner in
[requirements.json](../design-v2/planning/requirements.json). Every test has its
prerequisites, steps and independent expected outcomes in
[acceptance-tests.json](../design-v2/planning/acceptance-tests.json).
The [execution map](execution-map.json) adds actual legacy paths and environment
gates to every packet without changing the original graph.

The source package records 625 authoring checks. We verified the original
manifest's 19 file digests and performed the repository planning checks, but did
not reproduce those 625 checks: the reviewed validator returned exit 2 because
`jsonschema` is absent. Schema validation is BLOCKED. No dependency was installed.
The root planning checker does not substitute for full JSON Schema validation,
AT-078, G0 or any application suite.

## Repository adoption and WP-00 reconciliation

Already done: actual public fork `Brak23/mithril-voices`, correct parent/source,
checkout at `1c4c23f092fde34ce527ebb27309f57a8c5ec5bb`, and planning branch
`docs/implementation-plan`. The observed upstream main still matched that SHA
when checked for this plan. Original LICENSE/credits/history are preserved.

Do not create an empty repo, fork again, clone over this directory, reset, clean,
stash, rename the fork, or treat the current planning edits as disposable.
The source package's default name `lotro-voice-companion` is a template; the owner's
chosen `mithril-voices` destination controls. Actual scoped permissions are in
[authorization.json](authorization.json), separately from the source template.

The next scoped WP-00 branch must implement and test guarded bootstrap dry-run,
idempotence, dirty-path/tag/branch collisions, native-command failures and forbidden
remote writes before using its mutation path. Reuse the exact clone; add local
upstream push protection, disabled repository hooks, explicit push default and a
baseline tag/detached worktree only through the tested guarded process. Never move
an existing baseline tag. Experiments run in disposable copies with isolated user
data; reports belong outside the immutable baseline. Before any push, verify the
explicit fork URL/refspec and inspect the staged diff and inherited workflows.

This PR targets existing `main`. Creating/publishing `lvc/main`, changing the
default branch, enforcing branch protection and selecting a merge policy remain
separate setup decisions. There is no authorization to merge or publish a release.

## Milestones and acceptance gates

Each row is planned work, not a completion claim. Execute exact packet dependencies
and required AT IDs from [tasks.json](../design-v2/planning/tasks.json). Keep one
integration owner for core/schema/audio/migrations. Independent review is required
before integration; no parallel implementation agents are launched for this task.

| Stage | Packets and starting source | Deliverable and gate |
| --- | --- | --- |
| Audited baseline | WP-00; main.py, src/, tests/, pyproject.toml, uv.lock, installer/, plugins/, assets | Tested safe bootstrap, complete reuse/dependency/rights map, classified original tests; AT-076/077; G0 only with actual evidence |
| Foundation | WP-01; test fixtures/models and source contracts | Frozen verified environments, QA runner, independent fake clock/process/sink and original fixtures; AT-071/074/078; unavailable Windows lock qualification stays BLOCKED |
| Deterministic core | WP-02; replace src/engine.py coordination into lvc/core/ | Complete transition table, immutable IDs, page tombstones, priority Stop, bounded scheduler; AT-001/002/003/006/009/010/011/012/014/016/017/018/019/070/072; G1 core |
| Supervision | WP-03 after WP-02; TTS base/adapters and startup lifecycle | Strict JSON/LF QProcess transport, nonce/role/context checks, complete PCM spool and bounded deadlines; AT-007/008/009/044-049/084; G1 contract plus Windows process-tree qualification |
| Audio | WP-04 after WP-03; replace src/audio.py ownership | One renderer, generation fence/reset acknowledgment, sink epochs, drain and device behavior; AT-001/004/005/013/055/056; actual endpoint Stop measurements |
| Vision | WP-05 after WP-03; utils capture, calibrators, ocr.py | Verified native window identity, geometry epochs, qualified crop, conservative dual-pass OCR; AT-029-034/040-043/084; Windows capture probe |
| Manual alpha | WP-06 after WP-04/05; adapt Kokoro and splitter | Real approved CPU synthesis, Read/Preview/Stop through shared renderer; AT-050/052/054/061/069; G2 on actual Windows target |
| Optional hints | WP-07 after WP-03; replace watch_npc_file, audit Dt192 | Verified capabilities, own LVC namespace, bounded binary tailer; AT-020-028; bridge installation permission separate; bridge absence cannot block G2 |
| Automatic behavior | WP-08 after WP-06; retail callback and page tracking | Same-NPC transitions, qualified pages, conservative scroll ledger and negative cases; AT-010/011/012/016/017/019/033-035; G3 behavior |
| Voice identity | WP-09 after WP-06; voice library, backend selection/memory | Stable realization IDs, persisted casting, data-only lexicon and shared preview; AT-028/051/053/083 |
| Storage | WP-10 after WP-06; ConfigManager/JSON memory and DB | Single-writer SQLite, exact cache, transactional migrations/backups and disk floor; AT-004/057-059/065/085 |
| Desktop UX | WP-11 after WP-08/09/10; replace Gradio host role | Accessible Qt controls, diagnostic setup and idempotent legacy import; AT-014/015/018/043/055/065-067 |
| Premium adapter | WP-12 after WP-06/09; OmniVoice wrapper | Real GPU report or exact hardware/rights blocker; AT-047/048/050/054/081/083; disabled until qualified |
| Hardening | WP-13 after WP-07/11 | Offline/privacy, imports/archives, failures and rights map; AT-044/046/060/061/065/068/069/074/085 |
| Packaging | WP-14 after WP-13; replace legacy installer/update source | Relocatable bundles, clean user install, ownership, signed manifests/repair/rollback; AT-059/060/062-064/074 |
| Qualification | WP-15 after WP-14 | Frozen held-out evaluation, timing/game impact, soak and session evidence; AT-071-073/079/083; G3/G4 evidence |
| Release audit | WP-16 after WP-12/15 | Independent exact-candidate evidence/rights/support/recovery audit; AT-075-078/080; G4 only with owner publication authority |
| Optional corpus | WP-17 after WP-08/10 and separate scope | Authorized visible-span resolver and contradiction/held-out tests; AT-036-039/082; NOT_ENABLED until all conditional gates pass |

## First implementation sequence after planning approval

1. Finish WP-00 on a scoped branch. Audit all 82 statically discovered legacy test
   functions (not a pytest collection result), identify import/file/network side
   effects and classify the full collection in a reviewed disposable environment.
   Do not install the broad ML stack merely to run pure cases. Preserve failures.
2. Resolve local contract validation and the Windows builder/runtime boundary in
   WP-01. Build QA inventories that fail on zero tests, failed subprocesses and
   unexpected required skips. Keep schemas separate from runtime semantic checks.
3. Before coordinator code, add desired-behavior tests holding A's delayed result,
   then Stop/B start, and prove no A sink writes after fence acknowledgment. Add
   Stop-before-OCR, persistent tombstones, same-NPC B during A, full-queue Stop,
   duplicate terminal, stale sink and cache-hit races using barriers/virtual time.
4. Implement the pure reducer/scheduler and independent invariants. Quick runs
   require 1,000 reproducible schedules of up to 200 events; extended runs 10,000.
   Each named mutation must fail its regression: removed generation check, early
   tombstone expiry, altered digit, missing terminal, idle-as-completion.
5. Add process/audio/vision adapters without importing legacy startup into the host.
   Treat unavailable Windows capture/process/device evidence as a precise blocker,
   not a reason to fake completion or broaden the platform scope.

## Defect corrections and independent acceptance oracles

| Finding | Required correction | Evidence that must fail before the fix |
| --- | --- | --- |
| BUG-01 blocking retail/same-NPC interval | Asynchronous bounded observation; content/interaction identity | AT-010 B observed while A speaks; AT-011 duplicates do not replay; AT-012 close/reopen |
| BUG-02 shared stop event/unbounded queue | Immutable generation/request tokens, bounded reservations, final renderer fence | AT-001-006, including stale cache and old sink completion; no cooldown shortcut |
| BUG-03 missing producer terminal on exception | One effective terminal or host deadline; contained worker recovery | AT-007/008/009/047-049; no skipped failed unit or endless wait |
| BUG-04 watcher busy-spin/truncation/UTF-8 | Poll caps, byte offsets/identity, incremental decoder and namespaced records | AT-020-025; malformed/oversized/partial line then recovery |
| BUG-05 destructive OCR/reward/prefix cleanup | Preserve content, geometry exclusions and protected tokens | AT-030 exact `Bring 10 Ore. Do not trade 1.`; AT-031 lowercase; AT-032 in-body REWARDS; AT-033/034 clipped/disagreement |
| BUG-06 fuzzy substitution | Corpus off by default; optional strict visible-span resolver | AT-036-039/082; no high-score override of quantity/negation/stage contradictions |
| BUG-07 shallow streaming test | Actual coordinator/transport/sink lifecycle and mutation checks | AT-070; removing the real fence must turn a named test red |
| BUG-08 license/dependency mismatch | Rights inventory and separate exact runtime bundles | AT-060/062/074 and qualified rights review; no inferred license resolution |
| Additional source findings | Backend-specific save identity; stable voice IDs; fork-owned immutable update manifests | AT-051/066 plus added backend restart regression; AT-062/063; source audit records these as unexecuted risks |

## Measurement and release evidence

Required CPU warm first audio p95 <=1,500 ms; premium <=2,500 ms; exact-cache <=500 ms.
Wired Stop-to-silence p95 <=150 ms and maximum <=300 ms. At least 100 varied
measurements per timing category; nearest-rank p95, median/max/errors and cold/warm
status are reported. Count actual requested speech, not a beep or dispatch time.

Automatic qualification requires >=500 distinct positive screens, >=500 negatives
and >=100 held-out interaction sequences, split by quest/session family. Require
<=0.5% clear-crop character error, >=95% positive automatic coverage (abstentions
count against coverage), zero unsupported automatic speech and zero unintended
protected-token edits. Data remains private unless explicitly authorized for upload.

Require ten paired representative five-minute gameplay measurements, <=3% median
FPS loss and <=5% p99 frame-time increase versus game alone, with uncertainty.
Also require an eight-hour soak, <100 MiB sustained host growth excluding disclosed
bounded caches, 30 no-orphan startup/quit cycles and 30 interaction sessions across
three game launches. These are targets, all currently unmeasured. Voice fidelity
and rights are separate from preference; optional corpus requires >=3,000
independent accepted held-out matches with zero wrong substitutions.

Reports include tested SHA/dirty flag, spec/hash, exact command/exit, environment,
artifact/profile/fixture hashes and split, collected/passed/failed/skipped counts,
raw evidence paths and metrics. A Mac mock does not pass Windows/GPU/LOTRO cases.
G0 baseline, G1 deterministic core, G2 manual alpha, G3 automatic beta and G4 release
are earned separately. A missing optional activation can remain NOT_ENABLED.

## Upstream compatibility and data migration

Retain legacy `src/`, tests, launch scripts and credits until explicit replacement
tests exist. New modules live in `lvc/` and use narrow reviewed adapters. Test old
settings/voice imports on synthetic copies, with preview, hash records, conflicts
and idempotence; preserve originals and never auto-qualify old coordinates.

Use an immutable baseline and deliberate `integration/upstream-SHA` review for
later upstream changes. Compare licensing, dependencies, APIs, behavior and tests
before cherry-pick/merge. No startup `git pull`, upstream push or promise to track
every future release. The current installer still fetches upstream main and is not
a Mithril Voices release mechanism.

## Uncertainties and blockers

| ID | Status / smallest missing evidence | Affected work |
| --- | --- | --- |
| B-01 | BLOCKED: jsonschema absent; use a reviewed existing environment or explicitly scoped dev dependency setup | Full source/adopted package-schema rerun; no application pass claim |
| B-02 | NOT_RUN: guarded bootstrap/tests, baseline worktree/tag and complete isolated baseline test classification not executed in this planning-only task | WP-00/G0 remains incomplete |
| B-03 | BLOCKED: actual Windows 11 builder and clean binary/runtime smoke results | WP-01 exact locks; capture/audio/process/installer qualification |
| B-04 | BLOCKED: actual LOTRO/window/DPI/UI and output endpoint measurements | G2-G4, actual screen/Stop/game-impact claims |
| B-05 | UNVERIFIED: proposed GPU/display are target profiles, not measured current hardware | Premium and display-specific qualification |
| B-06 | BLOCKED for public packages: Apache root/MIT metadata discrepancy; asset/voice/data/Qt/native rights not qualified | Redistribution/signing/release; no runtime gate waiver |
| B-07 | UNVERIFIED: selected Qt capture adapter maps to native window identity and satisfies freshness/backend requirements | WP-05; propose bounded adapter decision if probe fails |
| B-08 | NOT_RUN: Lua capability probe and separately authorized own-namespace install | Optional hints only; base reader independent |
| B-09 | NOT_RUN: reviewed lvc/main/default-branch/protection/merge policy setup | Integration setup after planning PR review; this PR stays unmerged |
| B-10 | NOT_ENABLED: corpus/premium activation evidence and authorized assets unavailable | Optional profile gates only |

Do not infer approval to install software, enable workflows, use paid credits,
publish releases, upload private fixtures or contact a maintainer from this plan.
No document guarantees a flawless application. The next useful deliverable is the
bounded WP-00 completion described above, not a bulk implementation generated
without a verified baseline and test harness.
