# Alternate runs — merged 2026-08-21

A second summarization run of pk_006 (2010-05-18) and pk_008 (2010-08-17) was left
uncommitted in the working tree after wave 38. It was not a stale draft; it was a
complete independent run, and both runs validated 100% clean, so nothing in the
pipeline would have flagged the difference.

**pk_008 was merged.** The alternate contributed four figures the committed run
lacked — the Food Service ($925,233) and Adult and Community Education ($1,103,654)
fund balances, the July uncollected total ($133,236,042), and the Wattles easement
parcel (88-20-22-252-036, $1.00) — plus Bid #9687's August 3, 2010 open date and a
clearer reading of the August action items, where the award went to the VSC
microphones and the extension to the RKA fuel contract. The merged record is a
strict superset of both runs at 305 figures and is what D1 now holds.

Note on that last point: the committed phrasing ("awarding a diesel fuel contract
extension to RKA") was loose, not wrong — `page` and `verbose` both described the
extension correctly. The alternate's sentence was adopted for clarity, not as a
correction.

**pk_006 was left alone, deliberately.** Its alternate adds no figure and no proper
noun the committed text does not already carry, and drops sixteen figures. Every
difference is wording. Merging it could only have removed information. The check
that established this is worth repeating before trusting any future alternate:

    # figures, normalised the way validate_fanout does
    figs = lambda s: set(re.findall(r'\d{4,}(?:\.\d+)?', re.sub(r'[,\s]', '', s)))
    figs(alt) - figs(committed)          # empty  -> alternate adds nothing
    set(re.findall(r"\b[A-Z][a-zA-Z&'.-]{2,}\b", alt)) - same_for(committed)

Both files are kept as the record of what was compared.
