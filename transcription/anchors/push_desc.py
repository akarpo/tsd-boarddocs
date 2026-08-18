#!/usr/bin/env python3
"""Rebuild one meeting's YouTube description from its current D1 anchors."""
import json, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
import tsd_secrets
SITE = "https://tsd-boarddocs.karpowitsch.org"
MON = ["January","February","March","April","May","June","July","August",
       "September","October","November","December"]

def d1(sql):
    r = subprocess.run(["npx","wrangler","d1","execute","tsd-boarddocs","--remote",
                        "--json","--command",sql], cwd=REPO, capture_output=True, text=True)
    return json.loads(r.stdout)[0]["results"]

def token():
    d = urllib.parse.urlencode({"client_id": tsd_secrets.require("YT_CLIENT_ID"),
        "client_secret": tsd_secrets.require("YT_CLIENT_SECRET"),
        "refresh_token": tsd_secrets.require("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token"}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request(
        "https://oauth2.googleapis.com/token", d)))["access_token"]

def build(date):
    rec = d1(f"SELECT meeting_name, youtube_id FROM recordings WHERE meeting_date='{date}'")[0]
    name, vid = rec["meeting_name"], rec["youtube_id"]
    anc = d1(f"SELECT start_ms,label FROM transcript_anchors WHERE meeting_date='{date}' "
             f"AND meeting_name='{name.replace(chr(39), chr(39)*2)}' ORDER BY start_ms")
    n = name.lower()
    kind = ("Workshop Meeting" if "workshop" in n else "Winter Retreat" if "retreat" in n
            else "Organizational and Regular Meeting" if "organizational" in n else "Regular Meeting")
    y, m, d_ = date.split("-")
    url = f"{SITE}/?meeting=" + urllib.parse.quote(f"{date}|{name}", safe="")
    use_h = anc[-1]["start_ms"] >= 3600_000
    def ts(ms):
        s = ms // 1000
        return "0:00" if ms == 0 else (f"{s//3600}:{s%3600//60:02d}:{s%60:02d}" if use_h
                                       else f"{s//60}:{s%60:02d}")
    lines = [f"Troy School District Board of Education — {kind}, {MON[int(m)-1]} {int(d_)}, {y}.", "",
             "Full searchable transcript, agenda and board packet:", url, "",
             "Every line is speaker-attributed and searchable, and links to the agenda",
             "item and packet documents it refers to.", "", "Agenda"]
    lines += [f"{ts(a['start_ms'])} {a['label']}" for a in anc]
    lines += ["", f"Searchable archive of Troy School District board meetings: {SITE}"]
    return vid, "\n".join(lines)

def main_for(date):
    vid, desc = build(date)
    tok = token()
    u = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode({"part":"snippet","id":vid})
    cur = json.load(urllib.request.urlopen(urllib.request.Request(
        u, headers={"authorization": f"Bearer {tok}"})))["items"][0]["snippet"]
    body = {"id": vid, "snippet": {"title": cur["title"],
            "categoryId": cur.get("categoryId","25"), "description": desc}}
    for k in ("tags","defaultLanguage","defaultAudioLanguage"):
        if cur.get(k): body["snippet"][k] = cur[k]
    urllib.request.urlopen(urllib.request.Request(
        "https://www.googleapis.com/youtube/v3/videos?part=snippet",
        data=json.dumps(body).encode(), method="PUT",
        headers={"authorization": f"Bearer {tok}", "content-type":"application/json"}), timeout=60)
    import re as _re
    n = len(_re.findall(r"^\d+:\d{2}(?::\d{2})? ", desc, _re.M))
    print(f"{date} -> https://youtu.be/{vid}  ({len(desc)} chars, {n} chapters)")

def main():
    main_for(sys.argv[1])


if __name__ == "__main__":
    main()
