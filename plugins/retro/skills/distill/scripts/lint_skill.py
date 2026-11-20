"""Check a skill folder before it is installed: the parts every host needs, and nothing private in it.

    python lint_skill.py PATH/TO/SKILL_DIR [--max-words 1800] [--json]
    python lint_skill.py --recommendations FILE [--json]

Errors (exit 1): no SKILL.md; no frontmatter `name` or `description`; a name that is not lowercase-hyphenated or
doesn't match the folder; a `scripts/...` or `references/...` path the text names that doesn't exist; an email,
GUID, token, session link or a user's home path anywhere in the folder.
Warnings (exit 0): over --max-words; no numbered procedure; no section for what went wrong before (Gotchas,
Pitfalls, Known failures); no stated output (Output, Report, Deliverable); no budget line.

With --recommendations, the routing file distill writes (references/recommendations.md): each `## R<n>` block
needs Destination (one of check, test, access, guidance, skill, model, no-change), Observed with its evidence,
Measured, Existing, Change with a target (`-> file`, or `none` for no-change), Why and Verify. Private data is an
error there too. A Measured line claiming an improvement with nothing to compare it with is a warning.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcript as T  # noqa: E402

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REF_RE = re.compile(r"(?:<skill_root>/|(?<![\w/.-]))((?:scripts|references|assets)/[\w./-]+\.\w+)")
PRIVATE = [("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")), ("azure-devops-pat", T.ADO_PAT_RE),
           ("email", T.EMAIL_RE), ("guid", T.GUID_RE), ("token", T.TOKEN_RE), ("bearer", T.BEARER_RE),
           ("session-link", T.SESSION_URL_RE), ("home-path", re.compile(r"(?i)\b(?:[A-Z]:\\Users\\|/Users/)(?!\[user\])[^\\/\s'\"`<]+"))]
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "users.noreply.github.com", "anthropic.com")


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}
    out = {}
    for ln in m.group(1).splitlines():
        if ":" in ln and not ln.startswith(" "):
            k, v = ln.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def lint(folder: Path, max_words: int = 1800) -> tuple[list[str], list[str]]:
    folder = folder.resolve()  # `.` has no name of its own
    errors, warnings = [], []
    skill = folder / "SKILL.md"
    if not skill.exists():
        return [f"{folder}: no SKILL.md"], []
    text = skill.read_text(encoding="utf-8", errors="replace")
    fm = frontmatter(text)
    if not fm:
        errors.append("SKILL.md: no frontmatter (--- name / description ---)")
    for k in ("name", "description"):
        if fm and not fm.get(k):
            errors.append(f"SKILL.md: frontmatter has no {k}")
    name = fm.get("name", "")
    if name and not NAME_RE.match(name):
        errors.append(f"SKILL.md: name {name!r} is not lowercase words joined by hyphens")
    if name and name != folder.name:
        errors.append(f"SKILL.md: name {name!r} differs from the folder {folder.name!r} (hosts find a skill by its folder)")
    if fm.get("description") and len(fm["description"]) > 1024:
        errors.append("SKILL.md: description over 1024 characters")
    for ref in sorted(set(REF_RE.findall(text))):
        if not (folder / ref).exists():
            errors.append(f"SKILL.md names {ref}, which is not in the folder")
    for f in sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in (".md", ".py", ".json", ".txt", ".yaml", ".yml", ".sh", ".ps1")):
        body = f.read_text(encoding="utf-8", errors="replace")
        for i, ln in enumerate(body.splitlines(), 1):
            for kind, rx in PRIVATE:
                for m in rx.finditer(ln):
                    if kind == "email" and m.group(1).lower().endswith(ALLOWED_EMAIL_DOMAINS):
                        continue
                    errors.append(f"{f.relative_to(folder)}:{i}: {kind} (private data does not belong in a skill; use a placeholder)")
    body = re.sub(r"^---.*?\n---\s*\n", "", text, flags=re.S)
    words = len(body.split())
    if words > max_words:
        warnings.append(f"SKILL.md: {words} words, over {max_words}; move detail to references/")
    if not re.search(r"^\s*1\.\s", body, re.M):
        warnings.append("SKILL.md: no numbered procedure")
    if not re.search(r"^#+\s*(gotchas|pitfalls|known failures|what went wrong|traps)", body, re.I | re.M):
        warnings.append("SKILL.md: no Gotchas section (what failed in earlier runs and what to do instead)")
    if not re.search(r"^#+\s*(output|report|deliverable)", body, re.I | re.M):
        warnings.append("SKILL.md: no section saying what the run hands back")
    if not re.search(r"\bbudget\b", body, re.I):
        warnings.append("SKILL.md: no budget (tool calls or turns a run of it should take)")
    return errors, warnings


DESTINATIONS = ("check", "test", "access", "guidance", "skill", "model", "no-change")
REC_FIELDS = ("Destination", "Observed", "Measured", "Existing", "Change", "Why", "Verify")
FIELD_RE = re.compile(r"^\s*[-*]\s*\**(\w[\w -]*?)\**\s*:\s*(.*)$")
BETTER_RE = re.compile(r"(?i)\b(fewer|less|faster|slower|improv\w*|reduc\w*|cut|saved?|down from|up from|better|worse)\b|%")
COMPARED_RE = re.compile(r"(?i)\b(against|compared|vs\.?|versus|before|baseline|run-log|than)\b|->|→")


def _payload(text: str) -> str:
    """What a field holds once brackets, Markdown decoration and punctuation are taken off: empty means nothing."""
    return re.sub(r"[\s()\[\]`*_<>.,;:]+", "", text)


def lint_recommendations(path: Path) -> tuple[list[str], list[str]]:
    """The routing file: every block has its fields, a known destination, evidence and a target."""
    if not path.is_file():
        return [f"{path}: no such file"], []
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = [f"{path.name}: {kind} in the text" for kind, rx in PRIVATE if any(
        not (kind == "email" and m.group(0).lower().endswith(ALLOWED_EMAIL_DOMAINS)) for m in rx.finditer(text))]
    warnings: list[str] = []
    blocks = re.split(r"(?m)^##\s+", text)[1:]
    recs = [b for b in blocks if re.match(r"R\d+\b", b)]
    if not recs:
        return errors + [f"{path.name}: no `## R1: ...` block"], warnings
    for b in recs:
        rid = re.match(r"(R\d+)", b).group(1)
        fields: dict[str, str] = {}
        for line in b.splitlines()[1:]:
            m = FIELD_RE.match(line)
            if m and m.group(1).strip().title() in REC_FIELDS:
                fields[m.group(1).strip().title()] = m.group(2).strip()
        for f in REC_FIELDS:
            if not fields.get(f):
                errors.append(f"{rid}: no {f}")
        dest = fields.get("Destination", "").strip("` ").lower()
        if dest and dest not in DESTINATIONS:
            errors.append(f"{rid}: destination {dest!r} is not one of {', '.join(DESTINATIONS)}")
        obs = fields.get("Observed", "")
        # The marker isn't enough: something has to follow it (`evidence: )` is empty).
        ev = re.search(r"(?i)evidence\s*:(.*)", obs)
        if obs and (not ev or not _payload(ev.group(1))):
            errors.append(f"{rid}: Observed names no evidence (evidence: a step, a call, a file:line)")
        change = fields.get("Change", "")
        if change:
            if dest == "no-change" and change.lower().strip("` .") != "none":
                errors.append(f"{rid}: no-change has `Change: none`")
            arrow = re.split(r"->|→", change, maxsplit=1)
            if dest and dest != "no-change" and (len(arrow) < 2 or not _payload(arrow[1]) or not _payload(arrow[0])):
                errors.append(f"{rid}: Change names no target (`<what> -> <file or component>`)")
        measured = fields.get("Measured", "")
        if BETTER_RE.search(measured) and not COMPARED_RE.search(measured):
            warnings.append(f"{rid}: Measured claims a change with nothing to compare it with")
    return errors, warnings


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--recommendations", metavar="FILE", help="lint distill's routing file instead of a skill folder")
    ap.add_argument("--max-words", type=int, default=1800)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.folder and not a.recommendations:
        ap.error("a skill folder or --recommendations FILE")
    errors, warnings = lint_recommendations(Path(a.recommendations)) if a.recommendations else lint(Path(a.folder), a.max_words)
    if a.json:
        print(json.dumps({"errors": errors, "warnings": warnings}, indent=2))
    else:
        for e in errors:
            print(f"error: {e}")
        for w in warnings:
            print(f"warning: {w}")
        print(f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
