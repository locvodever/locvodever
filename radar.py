#!/usr/bin/env python3
"""repo radar: a day-by-day collection of GitHub repos worth remembering.

Lives in the profile repo. The full list goes to RADAR.md; the newest few are spliced into
README.md between the radar markers, so the rest of the profile README stays hand-written.

  python radar.py add <owner/name | url> [--why "..."] [--tags a,b] [--date YYYY-MM-DD]
  python radar.py note <owner/name> [--why "..."] [--tags a,b]   edit an existing entry
  python radar.py remove <owner/name>
  python radar.py refresh        re-pull description / stars / license for every entry
  python radar.py build          regenerate RADAR.md + the README section from repos.json
  python radar.py clone <owner/name>   clone it (checks out pinned_sha when the entry has one)
  python radar.py tags           list tags with counts

add / note / remove / refresh rebuild both, commit and push. Pass --no-git to skip that.
Metadata comes from the GitHub CLI (`gh api`), so run `gh auth login` once first.
Private repos are refused: this list is public.
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "repos.json"
README = ROOT / "README.md"
RADAR = ROOT / "RADAR.md"
START, END = "<!-- radar:start -->", "<!-- radar:end -->"
TZ = datetime.timezone(datetime.timedelta(hours=7))  # Asia/Ho_Chi_Minh, no DST
LATEST = 10
PROFILE_LATEST = 5


def run(*cmd, check=True):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=check)


def load():
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []


def save(entries):
    entries.sort(key=lambda e: (e["added"], e["repo"].lower()), reverse=True)
    DATA.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def slug(arg):
    m = re.search(r"(?:github\.com[/:])?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", arg.strip())
    if not m:
        sys.exit(f"not a GitHub repo: {arg}")
    return f"{m.group(1)}/{m.group(2)}"


def find(entries, repo):
    for e in entries:
        if e["repo"].lower() == repo.lower():
            return e
    return None


def tags_of(s):
    return sorted({t.strip().lower() for t in s.split(",") if t.strip()}) if s else []


def fetch(repo):
    """Live metadata for one repo; the canonical owner/name follows GitHub renames."""
    r = run("gh", "api", f"repos/{repo}", check=False)
    if r.returncode:
        sys.exit(f"gh api repos/{repo} failed: {r.stderr.strip()}")
    d = json.loads(r.stdout)
    return {
        "repo": d["full_name"],
        "url": d["html_url"],
        "description": d.get("description") or "",
        "language": d.get("language") or "",
        "license": (d.get("license") or {}).get("spdx_id") or "none",
        "stars": d.get("stargazers_count", 0),
        "private": d.get("private", False),
        "archived": d.get("archived", False),
    }


def cell(s):
    return (s or "—").replace("|", "\\|").replace("\n", " ")


def stars(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def row(e):
    name = f"[{e['repo']}]({e['url']})" + (" *(archived)*" if e.get("archived") else "")
    return f"| {name} | {cell(e['description'])} | {cell(e.get('why'))} | {stars(e.get('stars', 0))} | {e['added']} |"


def build(entries):
    head = "| Repo | What it is | Why I saved it | ★ | Added |\n|---|---|---|---|---|"
    tag_count = Counter(t for e in entries for t in e.get("tags", []))
    out = [
        "# Repo radar",
        "",
        "Repos worth remembering, collected day by day: what each one is, and why I saved it.",
        "Generated from [`repos.json`](repos.json) by [`radar.py`](radar.py), so don't edit this file by hand.",
        "",
        f"**{len(entries)} repos** · tags: " + " · ".join(f"[{t}](#{t}) ({n})" for t, n in sorted(tag_count.items())),
        "",
        "## Latest",
        "",
        head,
        *(row(e) for e in entries[:LATEST]),
    ]
    for t in sorted(tag_count):
        out += ["", f"## {t}", "", head, *(row(e) for e in entries if t in e.get("tags", []))]
    untagged = [e for e in entries if not e.get("tags")]
    if untagged:
        out += ["", "## untagged", "", head, *(row(e) for e in untagged)]
    out += [
        "",
        "## Adding one",
        "",
        "```sh",
        'python radar.py add owner/name --why "one line on why" --tags agents,learning',
        "python radar.py clone owner/name",
        "```",
        "",
        "Entries marked `source: ex-fork` in repos.json were forks I deleted on 2026-10-04; `pinned_sha` is the commit each fork had.",
        "",
    ]
    RADAR.write_text("\n".join(out), encoding="utf-8", newline="\n")
    splice_readme(entries)


def splice_readme(entries):
    """Replace the block between the radar markers in the profile README; the rest is hand-written."""
    lines = [START, "", "### Repos I've been saving", ""]
    for e in entries[:PROFILE_LATEST]:
        desc = e.get("why") or e.get("description")
        lines.append(f"- [{e['repo']}]({e['url']})" + (f" - {cell(desc)}" if desc else ""))
    lines += ["", f"[All {len(entries)} on the radar](RADAR.md)", "", END]
    block = "\n".join(lines)
    text = README.read_text(encoding="utf-8")
    if START in text and END in text:
        text = text[: text.index(START)] + block + text[text.index(END) + len(END):]
    else:
        text = text.rstrip("\n") + "\n\n" + block + "\n"
    README.write_text(text, encoding="utf-8", newline="\n")


def commit(msg, no_git):
    if no_git:
        return
    run("git", "add", "repos.json", "README.md", "RADAR.md")
    if run("git", "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("nothing changed")
        return
    run("git", "commit", "-q", "-m", msg)
    p = run("git", "push", "-q", check=False)
    print("committed and pushed" if p.returncode == 0 else f"committed; push failed: {p.stderr.strip()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["add", "note", "remove", "refresh", "build", "clone", "tags"])
    ap.add_argument("repo", nargs="?")
    ap.add_argument("--why")
    ap.add_argument("--tags")
    ap.add_argument("--date", help="override the added date (YYYY-MM-DD)")
    ap.add_argument("--no-git", action="store_true")
    a = ap.parse_args()
    entries = load()

    if a.cmd in ("add", "note", "remove", "clone") and not a.repo:
        ap.error(f"{a.cmd} needs a repo")

    if a.cmd == "add":
        meta = fetch(slug(a.repo))
        if meta["private"]:
            sys.exit(f"{meta['repo']} is private; the radar is public, so it stays off")
        if find(entries, meta["repo"]):
            sys.exit(f"{meta['repo']} is already on the radar; use `note` to edit it")
        added = a.date or datetime.datetime.now(TZ).date().isoformat()
        entries.append({**meta, "why": a.why or "", "tags": tags_of(a.tags), "added": added})
        msg = f"add {meta['repo']}"
    elif a.cmd == "note":
        e = find(entries, slug(a.repo)) or sys.exit(f"{a.repo} is not on the radar")
        if a.why is not None:
            e["why"] = a.why
        if a.tags is not None:
            e["tags"] = tags_of(a.tags)
        msg = f"note {e['repo']}"
    elif a.cmd == "remove":
        e = find(entries, slug(a.repo)) or sys.exit(f"{a.repo} is not on the radar")
        entries.remove(e)
        msg = f"remove {e['repo']}"
    elif a.cmd == "refresh":
        for e in entries:
            e.update(fetch(e["repo"]))
            print(f"refreshed {e['repo']}")
        msg = "refresh metadata"
    elif a.cmd == "clone":
        e = find(entries, slug(a.repo)) or {"repo": slug(a.repo)}
        dest = Path.cwd() / e["repo"].split("/")[1]
        if not dest.exists():
            subprocess.run(["git", "clone", f"https://github.com/{e['repo']}.git", str(dest)], check=True)
        if e.get("pinned_sha"):
            r = subprocess.run(["git", "-C", str(dest), "checkout", "-q", e["pinned_sha"]])
            if r.returncode:
                print(f"warn: {e['pinned_sha']} not found in {e['repo']}; left on the default branch")
        print(f"ok: {e['repo']} -> {dest}")
        return
    elif a.cmd == "tags":
        for t, n in Counter(t for e in entries for t in e.get("tags", [])).most_common():
            print(f"{n:4}  {t}")
        return
    else:
        build(entries)
        return

    save(entries)
    build(entries)
    commit(msg, a.no_git)


if __name__ == "__main__":
    main()
