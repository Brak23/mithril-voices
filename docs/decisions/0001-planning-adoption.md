# ADR 0001: adopt v2 requirements for planning on the existing fork

Status: RECORDED OWNER SCOPE for repository/destination/planning; no runtime waiver.

The owner requested a Khazad fork, then authorized project-specific implementation
planning documentation, a planning branch and reviewable PR. The selected fork is
`Brak23/mithril-voices`, publicly forked from `Thelukepet/Khazad-Voice-TTS`.
The v2 package was acquired after its completed response became accessible.
Authorization summaries deliberately exclude private chat text and identifiers.

## Adoption decisions

- Reuse the existing checkout and `docs/implementation-plan` branch at the audited
  commit. Do not run the new-clone/fork recipe in WP-00.
- Use the fork's existing `main` as the base of this documentation-only PR.
  `lvc/main`, `work/WP-XX-*`, baseline tag/worktree and default-branch changes are
  future repository bootstrap work, not silently completed setup. R-REP-001 through
  R-REP-003 remain unsatisfied as full implementation requirements.
- Preserve v2 text/JSON under `docs/design-v2/` to keep requirements separate from
  source runtime paths. Future WP-01 may promote contracts/catalogs to root paths
  through a mechanical reviewed move with checksum/link updates.
- The repository root instructions limit this task to documentation. The broad
  original adoption prompt and unset permission template inside the design do
  not erase existing owner authority or expand this task to application coding.
- Remove personal references from the published specification only; preserve
  behavior, thresholds, IDs, interfaces, test expectations and task dependencies.
  Omit DOCX and the authoring-time validation report. Record both source and
  adopted hashes rather than presenting modified files as byte-identical originals.
- Keep all application cases NOT_RUN and all source task definitions NOT_STARTED.
  Track actual adoption progress separately. The source validator assumes its
  template permissions/statuses remain unset; it is not an implementation ledger.

Affected IDs: R-GOV-001/002/004, R-REP-001/002/003/004, R-DEV-003. The product
contract remains v2.0; this is a repository adoption overlay, not a behavioral
specification change. No thresholds, release gates or platform choices are waived.

## Evidence and compatibility

The fork's parent/source and copied SHA were verified. No new application assets
are published. Legacy runtime, workflow, data, notices and history are unchanged.
The inherited Actions workflow responds to PRs targeting main; the planning commit
uses `[skip ci]` to honor the instruction not to run workflows. Pending skipped
checks are not test success and this task does not merge the PR.

Rollback: close the unmerged planning PR or revert its documentation commit through
normal review. Do not delete the fork, rewrite history, or alter the baseline.
