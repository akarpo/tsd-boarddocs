# The documents the archive could not read

`unparsed-documents.csv` is the full listing: 581 documents, one row each, with the
cause, the fix applied, characters before and after, and the outcome.

## What was wrong

The corpus holds 3,287 documents. **2,798 had extracted text; 489 had none at all** and
were therefore absent from D1 entirely — not summarized, not chunked, not searchable.
Another 92 had text that was technically present and practically worthless.

| | count | cause | fix |
|---|---:|---|---|
| A1 | 340 | `.doc` — no extractor bundled | `textutil -convert txt` |
| A2 | 137 | PDF with no text layer (scanned) | `ocrmypdf --force-ocr` |
| A3 | 5 | `.png` — no extractor | `tesseract` |
| A4 | 3 | legacy `.ppt` — no extractor | `soffice` → `.pptx` |
| A5 | 3 | `.docx` whose body is one embedded image | unzip `word/media/` → `tesseract` |
| A6 | 1 | a PDF named `.tmp` | magic-byte sniff |
| B1 | 1 | CID glyph ids (font has no ToUnicode CMap) | re-OCR |
| B2 | 91 | image-only pages | re-OCR |

**1.78M characters recovered.** Every A-group document now extracts; `_skipped.txt` went
from 490 entries to one, and that one is `_index/chunks.jsonl`, the pipeline's own index.

## Three things worth remembering

**An extension is a hint, not a fact.** `101811WkspMtg.tmp` is a PDF, and it was the only
file for the 2011-10-18 workshop — so a whole board meeting was missing from the archive
because of five characters in a filename. Unknown suffixes are now sniffed by magic bytes.

**"Extracted successfully" is not "extracted usefully."** Two failure modes produce output
that every downstream check accepts. A scanned page returns its header and nothing else. A
subset font with no ToUnicode CMap returns glyph ids — `/16/17/18/i255` — which have the
right *shape* and carry no words. Figure validation cannot see either, because neither
asserts a figure. `_needs_ocr()` tests three signals: emptiness, glyph runs, and source
bytes per extracted character. That last one matters on its own: a 2.3MB PDF that yielded
302 characters clears any per-page floor and is still a photograph. Real text costs a few
hundred source bytes per character; a scan costs thousands.

**Longer is not better when the incumbent is nonsense.** The first version of this fix kept
whichever result was longer, which is right for a thin scan — OCR either finds words or
honestly finds none — and exactly wrong for glyph garbage. The PEPS enrollment study
decoded to 82,353 characters of glyph ids and OCR'd to 31,257 characters of real text, so
"longer wins" preserved the nonsense. Garbage now never wins on length.

## What OCR could not fix

33 documents are still thin, and that is the honest answer rather than a failure: award
certificates, recognition graphics, and monthly wire-transfer reports for months with no
transactions. Several OCR'd *shorter* than their original extraction. They are listed with
outcome `unchanged (genuinely low content)`.
