# Alternate runs held for reconciliation

A second summarization run of pk_006 (2010-05-18) and pk_008 (2010-08-17) was left
uncommitted in the working tree after wave 38 and is preserved here. It is **not** a
superseded draft and **not** the version in D1.

Both runs validate 100% clean. The committed run is richer overall — 524 exact figures
against 431, verbose 14441/19709 against 12666/12152 — so it stays canonical and is what
`packets_out/` and D1 hold.

The alternate run is kept because it is not a strict subset:

* **It corrects a framing error.** Committed pk_008 reads "awarding a diesel fuel contract
  extension to RKA Petroleum"; the alternate reads "extending the diesel fuel contract with
  RKA Petroleum ... and awarding infrared classroom microphones to VSC". The award applied to
  the microphones, the extension to the fuel. `validate_fanout.py` cannot see this — the
  figures are identical in both — and it is the semantic-inversion class described in
  RESUMMARIZE.md.
* **It carries facts the committed run omits**, among them the Wattles easement parcel
  (88-20-22-252-036, $1.00), Bid #9687 opened 2010-08-03, the Food Service ($925,233) and
  Adult and Community Education ($1,103,654) fund balances, General Fund total revenue
  ($136,169,515 budgeted / $135,916,301 actual), Student Activity ($210,379.74) and Debt
  Funds ($29,971.77) ACH totals, and the 110/27/5 unit split behind the $74,641.00 VSC award.

Reconciling the two means a synthesis pass over both plus the source, then re-validating and
re-storing the merged text. Until that runs, the committed version stands.
