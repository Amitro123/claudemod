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
import sys


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
            if clear is not None and (not isinstance(clear, list) or any(not isinstance(x, str) for x in clear)):
                bad.append(f"{path}.complete.checked_clear: expected a list of strings")
    return len(bad) == n


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
        text = sys.stdin.read().strip()
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
        elif os.path.isfile(src):
            paths = [src]
        else:
            raise LeadsError(f"{src}: no such file or folder (give a folder of *.json, a .json file, or - for stdin)")
        for p in paths:
            name = os.path.basename(p)
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError) as exc:
                bad.append(f"{name}: invalid JSON or unreadable ({exc})")
                continue
            items += _accept(data, name, bad)
    if bad:
        raise LeadsError("; ".join(bad))
    return items


def leads_of(items: list[dict]) -> list[dict]:
    """A card gives its complete.siblings; a bare lead (has `where` or `what`) is itself. Each lead gets `case`."""
    out = []
    for x in items:
        c = x.get("complete")
        sibs = c.get("siblings") if isinstance(c, dict) else None
        for s in (sibs if sibs is not None else [x] if "where" in x or "what" in x else []):
            out.append({**s, "case": x.get("case") or x.get("unit") or s.get("case") or ""})
    return out
