# Automatic observation to core safety events (WP-02 slice)

`PageChangePending` is the core event for a credible changed panel before its
replacement OCR has been validated. It fences live work immediately while
retaining the old page identity and any Stop tombstone. An unconfirmed visual
change therefore cannot reauthorize the same stopped page. A later distinct
`ConfirmedPage` can initiate fresh validation. `PanelClosed` represents the
detector's second valid absence check: it fences live-panel work, clears the
interaction's read ledger, and permits a subsequent new interaction.

The synthetic integration test connects the automatic observation policy to
these reducer events and proves a late old-worker completion is discarded. The
test injects qualified observations; it does not qualify a LOTRO detector,
capture worker, resident voice supervisor, or physical Qt sink. The automatic
host callback that dispatches these events is still to be built. This packet
does not pass the full WP-02 transition table or G1/G3.
