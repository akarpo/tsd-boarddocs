"""Apply the authored speaker mapping + hand-off repairs to the 2026-09-24 LWV forum transcript.
Every edit asserts the original text it expects, so a drifted index fails loudly instead of
silently editing the wrong line. Fragments move ONLY where the person named is the speaker on
the other side of the boundary (see docs/TRANSCRIPTION.md, forum hand-off rule)."""
import json, copy, re
SRC = 'Troy School Board Meeting - 2026-09-24.transcript.json'
t = json.load(open(SRC)); U = copy.deepcopy(t['utterances'])
NAMES = {'A': 'Anjelica Miller', 'B': 'Mary Gunn', 'C': 'Vital Anne', 'D': 'Walt Cook', 'E': 'Beau Taylor'}
# --- whole-utterance edits: idx -> (expected original, replacement text, new cluster or None)
EDITS = {
  2:  ("All right, Ms. Sam.",      "All right, Ms. Anne.",   None),
  6:  ("Thank you. Ms. Gunn.",     "Thank you. Ms. Gunn.",   'A'),   # C -> moderator; Gunn (B) speaks next
  14: ("Ms. Gumm.",                "Ms. Gunn.",              'A'),   # C -> moderator; B next
  22: ("Ms. Gummel.",              "Ms. Gunn.",              None),
  26: ("Thank you. Ms. Alva.",     "Thank you. Ms. Anne.",   None),
  38: ("Masada.",                  "Ms. Anne.",              None),
  42: ("Gummel.",                  "Ms. Gunn.",              'A'),   # C -> moderator; B next
  46: ("Ms. Sano.",                "Ms. Anne.",              'A'),   # C cannot call her own name; Anne answers at #48/#50
  47: ("Ms. Sano?",                "Ms. Anne?",              None),
  53: ("Thank you, Miss Gunn.",    "Thank you. Ms. Gunn.",   None),
  60: ("Ms. Dunn.",                "Ms. Gunn.",              'A'),   # C -> moderator; B next
  63: ("Thank you. Masana.",       "Thank you. Ms. Anne.",   None),
  69: ("Rosanna.",                 "Ms. Anne.",              None),
}
for i, (orig, new, spk) in EDITS.items():
    assert U[i]['text'] == orig, (i, U[i]['text'])
    U[i]['text'] = new
    if spk: U[i]['speaker'] = spk
# --- in-text name normalizations (STT mishearings; each verified against the self-introductions)
SUBS = [('Angelica', 'Anjelica'), ('Vital Anna', 'Vital Anne'), ('Ms. Anna.', 'Ms. Anne.')]
for u in U:
    for a, b in SUBS: u['text'] = u['text'].replace(a, b)
# --- splits: a hand-off fragment glued onto a candidate's answer; moved to the moderator
def words(u): return u['words']
new = []
# #32 leading "Thank you. Ms. Anne." (C) -> moderator; Anne (C) is the speaker after the boundary
u = U[32]; assert u['text'].startswith("Thank you. Ms. Anne. Thank you, thank you, Anjelica."), u['text'][:80]
w = words(u); assert [x['text'] for x in w[:4]] == ['Thank', 'you.', 'Ms.', 'Anna.'], [x['text'] for x in w[:6]]
new.append(dict(speaker='A', text="Thank you. Ms. Anne.", start=w[0]['start'], end=w[3]['end'], confidence=u['confidence']))
u['text'] = u['text'][len("Thank you. Ms. Anne. "):]; u['start'] = w[4]['start']
# #41 trailing "Ms." (D) + #42 "Gummel." = the moderator's "Ms. Gunn."; Gunn (B) speaks next
u = U[41]; assert u['text'].endswith("educational experience Ms."), u['text'][-60:]
w = words(u); assert w[-1]['text'] == 'Ms.'
u['text'] = u['text'][:-len(" Ms.")]; u['end'] = w[-2]['end']
U[42]['start'] = w[-1]['start']
# #54 trailing "Mr. Taylor." (B) -> moderator; Taylor (E) speaks next
u = U[54]; assert u['text'].endswith("less costly. Mr. Taylor."), u['text'][-60:]
w = words(u); assert [x['text'] for x in w[-2:]] == ['Mr.', 'Taylor.']
new.append(dict(speaker='A', text="Mr. Taylor.", start=w[-2]['start'], end=w[-1]['end'], confidence=u['confidence']))
u['text'] = u['text'][:-len(" Mr. Taylor.")]; u['end'] = w[-3]['end']
# #61 trailing "Thank you, Mr. Taylor." (B): Gunn's own "Thank you." + the moderator's "Mr. Taylor."
u = U[61]; assert u['text'].endswith("it does work. Thank you, Mr. Taylor."), u['text'][-60:]
w = words(u); assert [x['text'] for x in w[-2:]] == ['Mr.', 'Taylor.']
new.append(dict(speaker='A', text="Mr. Taylor.", start=w[-2]['start'], end=w[-1]['end'], confidence=u['confidence']))
u['text'] = u['text'][:-len(" Thank you, Mr. Taylor.")] + " Thank you."; u['end'] = w[-3]['end']
for u in U: u.pop('words', None)
U.extend(new); U.sort(key=lambda x: x['start'])
for i, u in enumerate(U): u['idx'] = i; u['name'] = NAMES[u['speaker']]
def fmt(ms):
    s = ms // 1000; h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
def srt_ts(ms): return f"{ms//3600000:02d}:{(ms//60000)%60:02d}:{(ms//1000)%60:02d},{ms%1000:03d}"
json.dump(dict(id=t['id'], audio_duration=t['audio_duration'], speech_model_used=t.get('speech_model_used'),
               mapping=NAMES, utterances=U), open('lwv_2026-09-24.attributed.json', 'w'), indent=1)
with open('lwv_2026-09-24.attributed.txt', 'w') as f:
    for u in U: f.write(f"[{fmt(u['start'])}] {u['name']}: {u['text']}\n")
with open('lwv_2026-09-24.srt', 'w') as f:
    for u in U: f.write(f"{u['idx']+1}\n{srt_ts(u['start'])} --> {srt_ts(u['end'])}\n[{u['name']}] {u['text']}\n\n")
import collections
c = collections.Counter(u['name'] for u in U); print(len(U), "utterances;", dict(c))
print("--- short turns (<=8 words) after repair ---")
for u in U:
    if len(u['text'].split()) <= 8: print(f"  [{fmt(u['start'])}] {u['name']}: {u['text']}")
