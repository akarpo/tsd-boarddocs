# Facebook meeting notes — format and how to make them

After each board meeting the owner posts notes to the Facebook group **"Troy (MI) School
District Updates for Parents & Community Members"**
(https://www.facebook.com/groups/tsdytroymiupdates/), as **a post plus a first comment**:

- **the post** — a written summary of the meeting, in the format below;
- **the first comment** — the meeting's YouTube description, verbatim: the archive link and
  the timestamped agenda, one line per chapter.

Both are produced as Word files to open, select in full and paste. The source of each post is
kept in this repo as `facebook/<date>.md`; the Desktop copies get deleted after posting (the
2026-09-01 and 09-22 drafts were gone by 2026-10-10), so the repo is the record.

```bash
python3 scripts/facebook_notes.py facebook/2026-10-06.md --date 2026-10-06 \
  --transcript "transcripts/2026-10-06 - Troy (MI) School District - Board of Education - Workshop Meeting.txt"
# -> ~/Desktop/TSD Board Workshop 2026-10-06 - Facebook Post.docx
#    ~/Desktop/TSD Board Workshop 2026-10-06 - Facebook First Comment.docx
```

It runs **after** the whole meeting chain (OPERATIONS), because the first comment is the
YouTube description built from the authored chapters in D1, and the post's quotes are
checked against the attributed transcript.

---

## The post

Read from the posted 2026-09-01 workshop and 2026-09-22 regular-meeting notes on
2026-10-10, which is the authority here — not anyone's recollection of it.

| block | formatting | what goes in it |
|---|---|---|
| Title line | *italic* | `Troy School Board — Workshop Meeting, October 6, 2026` (regular: `— Regular Meeting, …`; a forum: the forum's own name) |
| Recording line | *`Meeting Recording - `* italic, link plain | `Meeting Recording - https://youtu.be/<id>` (a forum: `Forum Recording - `) |
| Lede | **bold**, one paragraph | What most of the meeting was about, then the rest in one sentence. Length in plain words ("this three hour, 48 minute workshop"). Remote attendance or an absence only when it is settled (see the rules). |
| Section headings | **bold**, plain language | One per topic, in meeting order. May make the point: "Commencement 2027 moves to weeknights", "The Digital Delusion: three years is too long". |
| Body | plain | Reporting prose. A person's full name on first mention, then the surname (Vital Anne → Anne). Figures as said or as printed in the packet. |
| Lists | `· ` at the start of the line | Purchases, calendars, trustee-by-trustee positions. The middle dot is literal text, not a Word list. |
| Short quotes | inline, in "double quotes" | A phrase or one sentence, attributed in the sentence. |
| Long quotes | own paragraph, *italic* | `"…" — Name`. One or two per post, for the line that carries a position. |
| Also at this meeting | **bold** heading, then `· ` lines | Public comment (or none), small items, the adjournment time. |
| One important caveat | **bold** heading, then one *italic* paragraph | What the reader should not over-read: a workshop votes on nothing and what comes back when; whose figures these are (the district's slides, a vendor's estimate, pre-Count Day counts); what was withheld. It is about the content, not about the transcript. |

Length has run about 1,700 words for a 2:50 workshop and about 2,000 for a 3:48 one.

## The first comment

Exactly the YouTube description (`transcription/anchors/push_desc.py`'s `build()`), which
the script fetches from D1:

```
Troy School District Board of Education — Workshop Meeting, October 6, 2026.

Full searchable transcript, agenda and board packet:
https://tsd-boarddocs.karpowitsch.org/?meeting=…

Every line is speaker-attributed and searchable, and links to the agenda
item and packet documents it refers to.

Agenda
0:00 1 Call to order; …
0:00:21 2.A Safety and security update: new director Paul Crane introduced
…
Searchable archive of Troy School District board meetings: https://tsd-boarddocs.karpowitsch.org
```

The chapter labels are the "additional summary" — write them (OPERATIONS step 5) as short
descriptive lines, because they are read here as well as on YouTube.

## Rules for the content

These come from errors that were caught, some of them only after publication.

1. **Every quote is in the transcript, word for word.** The script checks each quoted passage
   of four or more words against the attributed transcript and refuses (exit 1) when one is
   missing. Trim a quote with an ellipsis rather than tidy its grammar.
2. **Attribute only from the settled speaker spec.** Read the whole attributed transcript
   first; if a line reads as the wrong person, fix the spec and re-push before quoting it
   (2026-10-06: two of Anne's sentences had been duplicated under staff names).
3. **Presence and absence need evidence the post can stand on** — the chair's word, the
   minutes, or the owner. "Not heard" is not "absent"; leave it out rather than infer it.
   Remote attendance by Teams is stated when it is settled (the Teams active-speaker label,
   or the owner).
4. **Figures come from the packet or the slides, and the caveat says so.** Prefer the
   packet's exact amount when the speaker rounded ("just over $200,000"; $202,359.30 in the
   quote) and say whose number it is: a vendor's not-to-exceed is not a price.
5. **Report, don't grade.** Positions are attributed to the trustee or administrator who took
   them; the lede may say what most of the board wanted ("most trustees said it is too slow")
   only when the transcript shows it.
6. **A workshop votes on nothing.** Say which items come back to which regular meeting.

## Source syntax (`facebook/<date>.md`)

One block per line; blank lines are ignored.

| line | becomes |
|---|---|
| `*text*` | italic paragraph (title, caveat) |
| `**text**` | bold paragraph (lede, headings) |
| `Meeting Recording - URL` | italic label + plain link |
| `· text` | bullet line |
| `> text` | italic stand-alone quote |
| anything else | plain paragraph |

The script also refuses a post that does not open with title, recording line and lede, or
does not close with **One important caveat** and one italic paragraph. `--comment-file`
substitutes a text file for the D1 description (a recording that is not a board meeting).

## Reading a past post (for format questions)

The group search at `/groups/tsdytroymiupdates/search/?q=Meeting%20Recording` lists the
posts; their "Leave a comment" control opens the permalink with the comments. Through the
Chrome extension, `innerText` of the post container gives the text and its `<strong>` /
`<em>` elements give the formatting. Output containing the archive link is blocked by the
extension (it has a query string) — mask `?…` before returning it.
