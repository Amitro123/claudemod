#!/usr/bin/env python3
"""The one reader and validator for leads and case cards (lint_leads, handoff, crosscheck). Stdlib only.

Input: `-` (stdin), a folder of *.json, or a single .json file. Each holds an array or an object;
every lead or card is an object; `complete` (when the key is present, even as null) is an object and
`complete.siblings` (when present, even as null) is a list of objects (an explicit empty list is valid). Any violation raises LeadsError naming
the file and the item path, e.g. `merged.json[3].complete.siblings: expected a list`; callers exit 2
before they write anything.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

PROBE_DIR = "probes"
PROBE_KEYS = ("path", "leads", "ref", "command", "requires", "expect")
LEAD_SUFFIX_RE = re.compile(r" \[lead \d+\]$")
# A flag a model wrote as text can be a spelling of false: the schema shows `false | true | the question`.
NOT_SET = ("", "false", "no", "none", "null", "0")


CATEGORIES = ("security", "broken-flow", "hardening", "cost", "other")      # references/labels.md
REACHES = ("default-on", "conditional", "opt-in", "unknown")


def normalize_labels(lead: dict, who: str = "") -> list[str]:
    """Bring `category` and `reach` back to the values references/labels.md allows, in place; returns one line per
    change. A category outside the list becomes `other`; a reach outside it becomes `unknown`, and its text moves to
    `reach_when` when that is empty. What was written stays under `category_as_written` / `reach_as_written`.
    Measured on a live run (2026-11-15): 4 of 33 leads carried an invented category (`consistency`, `correctness`,
    `hygiene`, `test-gap`) and 4 a sentence in `reach`; the counts per category and per reach then mean nothing.
    A missing label is left missing: the handoff shows it as it always did."""
    notes = []
    tag = f"{who} " if who else ""
    c = lead.get("category")
    if isinstance(c, str) and c.strip():
        norm = c.strip().lower().replace("_", "-").replace(" ", "-")
        if norm in CATEGORIES:
            lead["category"] = norm
        else:
            lead["category_as_written"], lead["category"] = c, "other"
            notes.append(f"{tag}{lead.get('where')}: category '{c}' is not one of {', '.join(CATEGORIES)}; set to other")
    r = lead.get("reach")
    if isinstance(r, str) and r.strip():
        head, _, tail = r.strip().partition(":")
        norm = head.strip().lower().replace("_", "-").replace(" ", "-")
        if norm in REACHES:
            lead["reach"] = norm + (f": {tail.strip()}" if tail.strip() else "")
        else:
            lead["reach_as_written"], lead["reach"] = r, "unknown"
            if not str(lead.get("reach_when") or "").strip():
                lead["reach_when"] = " ".join(r.split())
            notes.append(f"{tag}{lead.get('where')}: reach '{' '.join(r.split())[:60]}' is not one of {', '.join(REACHES)}; "
                         "set to unknown, the text kept in reach_when")
    return notes


def flag_set(v: object) -> bool:
    """True for a set flag: true, or a non-empty string that does not spell false ("false", "no", "none"...)."""
    if isinstance(v, str):
        return v.strip().lower() not in NOT_SET
    return bool(v)


class LeadsError(ValueError):
    """Invalid leads or cards input; the message names every file and item path at fault."""


def _check(item: object, path: str, bad: list[str]) -> bool:
    if not isinstance(item, dict):
        bad.append(f"{path}: expected an object")
        return False
    n = len(bad)
    for k in ("culprit", "mechanism"):
        if item.get(k) is not None and not isinstance(item[k], dict):
            bad.append(f"{path}.{k}: expected an object")
    if "complete" in item:  # presence, not value: an explicit null is invalid too
        c = item["complete"]
        if not isinstance(c, dict):
            bad.append(f"{path}.complete: expected an object")
        else:
            if "siblings" in c:
                sibs = c["siblings"]
                if not isinstance(sibs, list):
                    bad.append(f"{path}.complete.siblings: expected a list")
                else:
                    bad += [f"{path}.complete.siblings[{j}]: expected an object"
                            for j, s in enumerate(sibs) if not isinstance(s, dict)]
            clear = c.get("checked_clear")
            if "checked_clear" in c and (not isinstance(clear, list) or any(not isinstance(x, str) for x in clear)):
                bad.append(f"{path}.complete.checked_clear: expected a list of strings")
    return len(bad) == n


def validate_leads(data: list, label: str) -> None:
    """Check a list of bare leads (a sweeper file, leads.json) with the same rules; raises LeadsError."""
    bad: list[str] = []
    for i, x in enumerate(data):
        _check(x, f"{label}[{i}]", bad)
    if bad:
        raise LeadsError("; ".join(bad))


def _accept(data: object, label: str, bad: list[str]) -> list[dict]:
    if isinstance(data, list):
        pairs = [(f"{label}[{i}]", x) for i, x in enumerate(data)]
    elif isinstance(data, dict):
        pairs = [(label, data)]
    else:
        bad.append(f"{label}: expected an array or an object")
        return []
    return [x for p, x in pairs if _check(x, p, bad)]


def read_items(src: str) -> list[dict]:
    """Every card or lead object from `src`, validated; raises LeadsError listing all problems."""
    items: list[dict] = []
    bad: list[str] = []
    if src == "-":
        text = sys.stdin.read().lstrip("\ufeff").strip()   # a BOM, as Windows PowerShell pipes write, like files
        if not text:
            raise LeadsError("stdin is empty; use [] for an intentionally empty result")
        dec, i = json.JSONDecoder(), 0
        while i < len(text):
            while i < len(text) and text[i] in " \t\r\n,":
                i += 1
            if i >= len(text):
                break
            try:
                obj, i = dec.raw_decode(text, i)
            except ValueError:
                bad.append(f"stdin at character {i}: invalid JSON")
                break
            items += _accept(obj, "stdin", bad)
    else:
        if os.path.isdir(src):
            paths = sorted(glob.glob(os.path.join(src, "*.json")))
            if not paths:
                # A folder with nothing in it read as zero leads, and the scripts went on as if all was checked.
                raise LeadsError(f"{src}: a folder with no *.json; give the cards folder, a .json file, or - for stdin")
        elif os.path.isfile(src):
            paths = [src]
        else:
            raise LeadsError(f"{src}: no such file or folder (give a folder of *.json, a .json file, or - for stdin)")
        for p in paths:
            name = os.path.basename(p)
            try:
                with open(p, encoding="utf-8-sig") as f:
                    data = json.load(f)
            except (OSError, ValueError) as exc:
                bad.append(f"{name}: invalid JSON or unreadable ({exc})")
                continue
            items += _accept(data, name, bad)
    if bad:
        raise LeadsError("; ".join(bad))
    return items


def _inside_probes(run_dir: str, parts: list[str]) -> bool:
    """The path, with every link resolved, is under `<run>/probes/` (that folder itself not a link elsewhere)."""
    root = os.path.normcase(os.path.join(os.path.realpath(run_dir), PROBE_DIR))
    target = os.path.normcase(os.path.realpath(os.path.join(run_dir, *parts)))
    try:
        return target != root and os.path.commonpath([root, target]) == root
    except ValueError:  # another drive on Windows
        return False


def probe_file_problems(lead: dict, run_dir: str, ref: str | None = None) -> list[str]:
    """What is wrong with a lead's saved probe (`probe_file`); [] when it has none, or when it is sound.

    The file must sit under `<run>/probes/` once links are resolved (no `..`, drive, UNC or `:` stream form) and exist; `leads` must name this lead's `where` (without a ` [lead N]`
    suffix); `ref`, when the run's ref is known, must be a prefix of it (or it of `ref`). Never raises."""
    pf = lead.get("probe_file")
    if pf is None:
        return []
    if not isinstance(pf, dict):
        return [f"probe_file: expected an object with {', '.join(PROBE_KEYS)}"]
    out = [f"probe_file.{k}: missing or empty" for k in PROBE_KEYS if pf.get(k) in (None, "", [], {})]
    path = pf.get("path")
    if isinstance(path, str) and path:
        parts = path.replace("\\", "/").split("/")
        if os.path.isabs(path) or path.startswith(("/", "\\")) or ":" in path or ".." in parts \
                or parts[0] != PROBE_DIR or len(parts) < 2 or not parts[-1]:
            out.append(f"probe_file.path {path}: not a path under {PROBE_DIR}/ in the run folder")
        elif not _inside_probes(run_dir, parts):
            out.append(f"probe_file.path {path}: resolves outside {PROBE_DIR}/ in the run folder (a link?)")
        elif not os.path.isfile(os.path.join(run_dir, *parts)):
            out.append(f"probe_file.path {path}: missing from the run folder")
    names = pf.get("leads")
    own = LEAD_SUFFIX_RE.sub("", str(lead.get("where") or ""))
    if names not in (None, "", []):
        if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
            out.append("probe_file.leads: expected a list of the leads' `where`")
        elif own not in {LEAD_SUFFIX_RE.sub("", x) for x in names}:
            out.append(f"probe_file.leads: does not name this lead ({own})")
    made_at = pf.get("ref")
    if ref and isinstance(made_at, str) and made_at and not (ref.startswith(made_at) or made_at.startswith(ref)):
        out.append(f"probe_file.ref {made_at}: not the run's ref {ref[:12]}")
    return out


def leads_of(items: list[dict]) -> list[dict]:
    """A card gives its complete.siblings; a bare lead (has `where` or `what`) is itself. Each lead gets `case`."""
    out = []
    for x in items:
        c = x.get("complete")
        sibs = c.get("siblings") if isinstance(c, dict) else None
        for s in (sibs if isinstance(sibs, list) else [x] if "where" in x or "what" in x else []):
            out.append({**s, "case": x.get("case") or x.get("unit") or s.get("case") or ""})
    return out


# Shared by merge_cards.py and merge_verdicts.py (--repair-escapes): an agent on Windows writes C:\Users raw,
# and \U is no JSON escape (2026-11-15, a sweep file and a verdicts file of one run).
_ESC_RE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})|\\')


def _double_stray(m: "re.Match[str]") -> str:
    return m.group(0) if m.group(1) else "\\\\"


def repair_escapes(path: str, exc: Exception) -> bool:
    """Double stray backslashes in `path` when `exc` is an invalid-escape error; True when repaired and re-parsed.

    The original bytes are kept as `<path>.orig`; the file is rewritten only after the repaired text parses."""
    if not isinstance(exc, json.JSONDecodeError) or "escape" not in exc.msg:
        return False
    with open(path, "rb") as f:
        raw = f.read()
    fixed = _ESC_RE.sub(_double_stray, raw.decode("utf-8-sig"))
    try:
        json.loads(fixed)
    except ValueError:
        return False
    with open(path + ".orig", "wb") as f:
        f.write(raw)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(fixed)
    return True
