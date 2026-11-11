#!/usr/bin/env python3
"""Check the artifacts of a finished run against a profile. Stdlib only, read-only on the run folder.

    python check_run.py RUN_FOLDER [--profile profile.json] [--override file.json] [--expect 1,2,3] [--report out.json]

Reads profile.json (default: next to this script) and checks every invariant it lists. It imports nothing
from the plugin: file names, fields and log formats come from the profile. Prints one JSON report on
stdout: {"run", "profile", "ok", "invariants": [{"id", "status": pass|fail|skipped, "evidence"}]}.
`--override` deep-merges a JSON object onto the profile (use it when a run folder names files differently).
When `<run>/plan/expect.json` exists (written by the plugin's plan.py) it replaces the command line: the reader ids,
the sweeper files and the verifier verdict files come from it, and the extra invariant `plan.phases` fails when a
planned phase left its outputs missing or invalid (the model skipped the phase), or when no verify phase was planned.
`--report` writes the same JSON elsewhere; a path inside the run folder is refused (exit 2).
Exit 0 all invariants pass or are skipped, 1 at least one fails, 2 invalid input (no run folder, unreadable
or invalid profile or override, unknown invariant id, bad --report path).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

CHECKS: dict = {}


class Invalid(Exception):
    pass


def _bad_const(name):
    raise ValueError(f"non-standard JSON constant {name}")


def load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read(), parse_constant=_bad_const)


def deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def dig(obj, dotted: str):
    if dotted == "$":
        return obj
    for part in dotted.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def read_text(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


class Run:
    """Everything read from the run folder, once. Problems are recorded, never raised."""

    def __init__(self, folder: str, prof: dict, expect: list[str] | None, plan: dict | None = None):
        self.folder, self.p, self.plan = folder, prof, plan
        self.F = prof.get("fields", {})
        self.expect = expect
        self.paths: dict[str, list[str]] = {}
        self.missing: list[str] = []
        self.invalid: list[str] = []
        self.data: dict[str, object] = {}
        self.ids: list[str] = []
        self._discover()

    def f(self, key: str) -> str:
        return self.F.get(key, key)

    def _glob(self, pattern: str) -> list[str]:
        return sorted(glob.glob(os.path.join(self.folder, *pattern.split("/"))))

    def _discover(self) -> None:
        for name, a in self.p["artifacts"].items():
            pat = a["path"]
            if a.get("per_id"):
                found = self._glob(pat.replace("{id}", "*"))
                found_ids = [self._id_of(pat, x) for x in found]
                ids = self.expect if self.expect else found_ids
                self.ids = list(ids)
                self.paths[name] = [os.path.join(self.folder, *pat.replace("{id}", i).split("/")) for i in ids]
                for i, pth in zip(ids, self.paths[name]):
                    if not os.path.isfile(pth):
                        self.missing.append(pat.replace("{id}", i))
            elif isinstance(a.get("files"), list):
                self.paths[name] = [os.path.join(self.folder, *f.split("/")) for f in a["files"]]
                for f, pth in zip(a["files"], self.paths[name]):
                    if not os.path.isfile(pth):
                        self.missing.append(f)
            else:
                self.paths[name] = self._glob(pat)
                if not self.paths[name]:
                    if a.get("required"):
                        self.missing.append(pat)
                    elif a.get("min", 0) > 0:
                        self.missing.append(f"{pat} (at least {a['min']})")
                elif len(self.paths[name]) < a.get("min", 0):
                    self.missing.append(f"{pat} (found {len(self.paths[name])}, need {a['min']})")
        for name, a in self.p["artifacts"].items():
            for pth in self.paths[name]:
                if not os.path.isfile(pth):
                    continue
                rel = os.path.relpath(pth, self.folder).replace("\\", "/")
                kind = a.get("kind", "json")
                if kind == "text":
                    t = read_text(pth)
                    if t is None:
                        self.invalid.append(f"{rel}: unreadable text")
                    else:
                        self.data[rel] = t
                    continue
                try:
                    d = load_json(pth)
                except (OSError, ValueError) as exc:
                    self.invalid.append(f"{rel}: {str(exc)[:80]}")
                    continue
                if kind == "json-array" and not isinstance(d, list):
                    self.invalid.append(f"{rel}: expected an array")
                    continue
                if kind == "json" and not isinstance(d, (dict, list)):
                    self.invalid.append(f"{rel}: expected an object or array")
                    continue
                self.data[rel] = d

    @staticmethod
    def _id_of(pattern: str, path: str) -> str:
        pre, post = pattern.split("{id}")
        base = os.path.basename(path)
        return base[len(os.path.basename(pre)):len(base) - len(post)] if post else base

    def rel(self, pth: str) -> str:
        return os.path.relpath(pth, self.folder).replace("\\", "/")

    def items(self, name: str):
        """[(relative file, parsed)] for the readable files of an artifact."""
        out = []
        for pth in self.paths.get(name, []):
            r = self.rel(pth)
            if r in self.data:
                out.append((r, self.data[r]))
        return out

    def leads_of(self, name: str, rel: str, d) -> list:
        at = self.p["artifacts"][name].get("leads_at", "$")
        items = d if isinstance(d, list) else [d]
        out = []
        for it in items:
            v = dig(it, at) if at != "$" else it
            if at == "$":
                out.append(it)
            elif isinstance(v, list):
                out += v
        return out

    def input_leads(self):
        """{file: [lead objects]} for every lead input (artifacts with leads_at)."""
        res = {}
        for name, a in self.p["artifacts"].items():
            if "leads_at" not in a:
                continue
            for rel, d in self.items(name):
                res[rel] = [x for x in self.leads_of(name, rel, d) if isinstance(x, dict)]
        return res

    def one(self, name: str):
        its = self.items(name)
        return its[0] if its else (None, None)

    def where(self, lead: dict) -> str:
        return str(lead.get(self.f("where")))


def check(cid):
    def deco(fn):
        CHECKS[cid] = fn
        return fn
    return deco


def res(status: str, evidence: str):
    return status, evidence


def short(xs, n=5):
    xs = list(xs)
    return ", ".join(map(str, xs[:n])) + (f" (+{len(xs) - n} more)" if len(xs) > n else "")


def log_counts(r: Run):
    """(raw, merges) from the dedupe log per the profile, or None."""
    rel, text = r.one("dedupe_log")
    if text is None:
        return None
    cfg = r.p.get("dedupe_log", {})
    m = re.search(cfg.get("raw_count", r"^- raw: (\d+)\s*$"), text, re.M)
    if not m:
        return None
    heading, none = cfg.get("merges_heading", "## Merges"), cfg.get("none_marker", "- none")
    merges, inside = 0, False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == heading
        elif inside and line.startswith("- ") and line.strip() != none:
            merges += 1
    return int(m.group(1)), merges


@check("artifacts.present")
def _present(r: Run):
    if r.expect is None and not r.p.get("expect_ids") and not r.ids and r.p["artifacts"].get("cards", {}).get("required"):
        return res("fail", "no cards found and no expected ids given")
    if r.missing:
        return res("fail", "missing: " + short(r.missing, 12))
    return res("pass", f"{sum(len(v) for v in r.paths.values())} files found; {len(r.ids)} reader ids")


@check("artifacts.valid_json")
def _valid(r: Run):
    if r.invalid:
        return res("fail", "invalid: " + short(r.invalid, 12))
    return res("pass", f"{len(r.data)} files parsed")


@check("inputs.match_log_raw")
def _inputs(r: Run):
    """Silent-drop detector: every lead of every input file must be in the raw count of the dedupe log and in leads.json."""
    ins = r.input_leads()
    lc = log_counts(r)
    lrel, leads = r.one("leads")
    if not ins or lc is None or leads is None:
        return res("skipped", "needs input files, a dedupe log with a raw count and leads.json")
    total = sum(len(v) for v in ins.values())
    # supply: leads.json winners plus the losers recorded in merged_from
    supply = Counter(r.where(x) for x in leads if isinstance(x, dict))
    for x in leads:
        if isinstance(x, dict) and isinstance(x.get(r.f("merged_from")), list):
            supply.update(str(w) for w in x[r.f("merged_from")])
    lost: dict[str, int] = {}
    for rel, items in ins.items():
        for x in items:
            w = r.where(x)
            if supply[w] > 0:
                supply[w] -= 1
            else:
                lost[rel] = lost.get(rel, 0) + 1
    problems = []
    if total != lc[0]:
        problems.append(f"inputs hold {total} leads ({', '.join(f'{k}: {len(v)}' for k, v in ins.items())}) but the dedupe log says raw {lc[0]}")
    if lost:
        problems.append("leads missing from " + lrel + ": " + ", ".join(f"{k} ({n} of {len(ins[k])})" for k, n in lost.items()))
    if problems:
        return res("fail", "; ".join(problems))
    return res("pass", f"{total} input leads in {len(ins)} files equal raw {lc[0]}")


@check("leads.source")
def _source(r: Run):
    ins = r.input_leads()
    lrel, leads = r.one("leads")
    if leads is None or not ins:
        return res("skipped", "needs leads.json and input files")
    known = {r.where(x) for items in ins.values() for x in items}
    ok_by = set(r.ids) | {i for i in r.ids} | {"sweeper"}
    fb = r.f("found_by")
    bad = []
    for x in leads:
        if not isinstance(x, dict):
            bad.append("non-object lead")
            continue
        origin = {r.where(x)} | {str(w) for w in (x.get(r.f("merged_from")) or [])}
        by = str(x.get(fb))
        if not (origin & known) or (fb in x and by not in ok_by):
            bad.append(r.where(x))
    if bad:
        return res("fail", f"{len(bad)} of {len(leads)} leads without a source in the inputs: " + short(bad))
    return res("pass", f"{len(leads)} leads, each traced to a card or sweep file")


@check("leads.count")
def _count(r: Run):
    ins = r.input_leads()
    lc = log_counts(r)
    lrel, leads = r.one("leads")
    if not ins or lc is None or leads is None:
        return res("skipped", "needs input files, a dedupe log with a raw count and leads.json")
    total = sum(len(v) for v in ins.values())
    want = total - lc[1]
    if len(leads) != want:
        return res("fail", f"{lrel} has {len(leads)} leads; inputs {total} minus {lc[1]} exact-duplicate merges in the log = {want}")
    return res("pass", f"{len(leads)} = {total} - {lc[1]}")


@check("verdicts.no_orphans")
def _orph(r: Run):
    lrel, leads = r.one("leads")
    vs = r.items("verdicts")
    if leads is None:
        return res("skipped", "needs leads.json")
    if not vs:
        return res("skipped", "no verdict files")
    known = {r.where(x) for x in leads if isinstance(x, dict)}
    orphans = [(rel, r.where(v)) for rel, d in vs for v in d if isinstance(v, dict) and r.where(v) not in known]
    n = sum(len(d) for _, d in vs)
    if orphans:
        return res("fail", f"{len(orphans)} verdicts name a where absent from leads: " + short(f"{a}:{w}" for a, w in orphans))
    return res("pass", f"{n} verdicts in {len(vs)} files all match a lead")


def unverified(r: Run, merged: list) -> list[str]:
    vf = r.f("verdict")
    vals = {v.lower() for v in r.p.get("unverified_values", ["unverified"])}
    return [r.where(x) for x in merged if isinstance(x, dict) and str(x.get(vf) or "unverified").lower() in vals]


@check("verdicts.coverage")
def _cov(r: Run):
    mrel, merged = r.one("merged")
    if merged is None:
        return res("skipped", "needs merged.json")
    un = unverified(r, merged)
    if not un:
        return res("pass", f"all {len(merged)} leads have a verdict")
    hrel, text = r.one("handoff")
    if text is None:
        return res("fail", f"{len(un)} leads have no verdict and there is no handoff to carry a banner")
    first = next((line for line in text.splitlines() if line.strip()), "")
    m = re.search(r.p.get("handoff", {}).get("banner", r"^UNVERIFIED: (\d+) of (\d+)"), first)
    if not m:
        return res("fail", f"{len(un)} of {len(merged)} leads have no verdict and the handoff's first line is not the UNVERIFIED banner")
    if int(m.group(1)) != len(un):
        return res("fail", f"banner says {m.group(1)} unverified, merged.json has {len(un)}")
    return res("pass", f"{len(un)} unverified leads and the handoff banner says {m.group(1)}")


@check("merged.matches_leads")
def _merged(r: Run):
    lrel, leads = r.one("leads")
    mrel, merged = r.one("merged")
    if leads is None or merged is None:
        return res("skipped", "needs leads.json and merged.json")
    lw = Counter(r.where(x) for x in leads if isinstance(x, dict))
    mw = Counter(r.where(x) for x in merged if isinstance(x, dict))
    dropped = {v.upper() for v in r.p.get("dropped_verdicts", [])}
    verdict_of = {}
    for rel, d in r.items("verdicts"):
        for v in d:
            if isinstance(v, dict):
                verdict_of[r.where(v)] = str(v.get(r.f("verdict")) or "").upper()
    extra = [w for w in mw if w not in lw]
    gone = [w for w in lw if mw[w] < lw[w] and verdict_of.get(w) not in dropped]
    problems = []
    if extra:
        problems.append(f"{len(extra)} merged leads not in leads.json: " + short(extra))
    if gone:
        problems.append(f"{len(gone)} leads missing from merged.json without a dropped verdict: " + short(gone))
    if problems:
        return res("fail", "; ".join(problems))
    return res("pass", f"merged {sum(mw.values())} leads from {sum(lw.values())}")


@check("handoff.counts")
def _handoff(r: Run):
    mrel, merged = r.one("merged")
    hrel, text = r.one("handoff")
    if merged is None or text is None:
        return res("skipped", "needs merged.json and the handoff")
    rows, after_sep = 0, False
    rej = r.p.get("handoff", {}).get("rejected_prefix", "- `")
    rejected = 0
    for line in text.splitlines():
        if re.match(r"^\|[\s\-:|]+\|\s*$", line):
            after_sep = True
        elif after_sep and line.startswith("|"):
            rows += 1
        elif line.startswith(rej):
            rejected += 1
    placeholder = rows == 1 and re.search(r"no leads", text)
    shown = 0 if placeholder else rows
    if shown + rejected != len(merged):
        return res("fail", f"handoff shows {shown} rows + {rejected} rejected entries; merged.json has {len(merged)} leads")
    return res("pass", f"{shown} rows + {rejected} rejected = {len(merged)}")


def safe_rel(f) -> bool:
    return isinstance(f, str) and bool(f) and not os.path.isabs(f) and ".." not in f.replace("\\", "/").split("/")


def load_plan(folder: str):
    """The parsed `plan/expect.json`, or None when the run has no plan. Raises Invalid for an unreadable or malformed plan."""
    path = os.path.join(folder, "plan", "expect.json")
    if not os.path.isfile(path):
        return None
    try:
        d = load_json(path)
    except (OSError, ValueError) as exc:
        raise Invalid(f"plan/expect.json unreadable: {exc}")
    if not isinstance(d, dict) or d.get("plan_version") != 1 or d.get("mode") not in ("none", "single", "parallel"):
        raise Invalid("plan/expect.json: needs plan_version 1 and a mode (none, single, parallel)")
    for key in ("reader_ids", "sweeper_files", "phases", "verifier_chunks"):
        if not isinstance(d.get(key), list):
            raise Invalid(f"plan/expect.json: `{key}` must be a list")
    for ph in d["phases"]:
        if not (isinstance(ph, dict) and isinstance(ph.get("name"), str) and isinstance(ph.get("min_agents"), int)
                and isinstance(ph.get("outputs"), list) and all(safe_rel(o) for o in ph["outputs"])):
            raise Invalid("plan/expect.json: every phase needs a name, an integer min_agents and relative `outputs`")
    if not all(isinstance(x, str) and re.fullmatch(r"[\w.\-]+", x) for x in d["reader_ids"]):
        raise Invalid("plan/expect.json: reader ids must be plain names")
    if not all(safe_rel(f) for f in d["sweeper_files"]) or not all(
            isinstance(c, dict) and safe_rel(c.get("verdicts")) for c in d["verifier_chunks"]):
        raise Invalid("plan/expect.json: file names must be relative and stay in the run folder")
    return d


def apply_plan(prof: dict, plan: dict) -> list[str] | None:
    """Make the profile follow the plan; returns the expected reader ids (None when there are no readers)."""
    arts = prof["artifacts"]
    if plan["mode"] == "parallel":
        if "sweeps" in arts:
            arts["sweeps"] = {**arts["sweeps"], "files": list(plan["sweeper_files"])}
        if "verdicts" in arts:
            arts["verdicts"] = {**arts["verdicts"], "files": [c["verdicts"] for c in plan["verifier_chunks"]]}
    else:
        for k in ("cards", "sweeps", "dedupe_log"):
            arts.pop(k, None)
        if "verdicts" in arts:
            arts["verdicts"] = {**arts["verdicts"], "files": [c["verdicts"] for c in plan["verifier_chunks"]]}
    if "plan.phases" not in prof["invariants"]:
        prof["invariants"] = [*prof["invariants"], "plan.phases"]
    return list(plan["reader_ids"]) if plan["mode"] == "parallel" else None


@check("plan.phases")
def _phases(r: Run):
    plan = r.plan
    if plan is None:
        return res("skipped", "the run has no plan/expect.json")
    if plan["mode"] == "none":
        return res("pass", "the plan had no case to work")
    names = [ph["name"] for ph in plan["phases"]]
    problems = []
    if "verify" not in names:
        problems.append("no verify phase was planned (plan.py --phase verify was not run): verification is required")
    for ph in plan["phases"]:
        absent, broken = [], []
        for o in ph["outputs"]:
            pth = os.path.join(r.folder, *o.split("/"))
            if not os.path.isfile(pth):
                absent.append(o)
            elif o.endswith(".json"):
                try:
                    if not isinstance(load_json(pth), (dict, list)):
                        broken.append(o)
                except (OSError, ValueError):
                    broken.append(o)
            elif os.path.getsize(pth) == 0:
                broken.append(o)
        if absent:
            problems.append(f"phase {ph['name']!r} skipped or unfinished: missing {short(absent, 8)} (planned {ph['min_agents']} agents)")
        if broken:
            problems.append(f"phase {ph['name']!r}: invalid or empty {short(broken, 8)}")
    if problems:
        return res("fail", "; ".join(problems))
    n = sum(ph["min_agents"] for ph in plan["phases"])
    return res("pass", f"{len(plan['phases'])} phases ({', '.join(names)}), {n} planned agents, every planned output present and valid")


def validate_profile(p) -> None:
    if not isinstance(p, dict) or not isinstance(p.get("artifacts"), dict) or not isinstance(p.get("invariants"), list):
        raise Invalid("profile needs an `artifacts` object and an `invariants` list")
    for k, a in p["artifacts"].items():
        if not isinstance(a, dict) or not isinstance(a.get("path"), str):
            raise Invalid(f"artifact {k!r} needs a string `path`")
    for cid in p["invariants"]:
        if cid not in CHECKS:
            raise Invalid(f"unknown invariant id {cid!r}; known: {', '.join(sorted(CHECKS))}")


def inside(path: str, folder: str) -> bool:
    a, b = os.path.realpath(path), os.path.realpath(folder)
    return a == b or a.startswith(b + os.sep)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run")
    ap.add_argument("--profile", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json"))
    ap.add_argument("--override")
    ap.add_argument("--expect")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    try:
        if not os.path.isdir(a.run):
            raise Invalid(f"{a.run}: not a folder")
        if a.report and inside(a.report, a.run):
            raise Invalid("--report must not be inside the run folder")
        try:
            prof = load_json(a.profile)
            if a.override:
                ov = load_json(a.override)
                if not isinstance(ov, dict):
                    raise Invalid("override must be a JSON object")
                prof = deep_merge(prof, ov)
        except (OSError, ValueError) as exc:
            raise Invalid(f"profile or override unreadable: {exc}")
        validate_profile(prof)
        plan = load_plan(a.run)
        planned = apply_plan(prof, plan) if plan else None
        expect = None
        raw = a.expect if a.expect is not None else prof.get("expect_ids")
        if isinstance(raw, list):
            raw = ",".join(map(str, raw))
        if raw:
            expect = [x.strip() for x in str(raw).split(",") if x.strip()]
            if len(set(expect)) != len(expect):
                raise Invalid("expected ids must be distinct")
        if plan and plan["mode"] == "parallel":
            expect = planned  # the plan, not the command line, says which readers were started
        for bad_re in (prof.get("dedupe_log", {}).get("raw_count"), prof.get("handoff", {}).get("banner")):
            if bad_re:
                try:
                    re.compile(bad_re)
                except re.error as exc:
                    raise Invalid(f"bad regex in profile: {exc}")
    except Invalid as exc:
        print(f"check_run.py: {exc}", file=sys.stderr)
        return 2
    run = Run(a.run, prof, expect, plan)
    out = []
    for cid in prof["invariants"]:
        status, ev = CHECKS[cid](run)
        out.append({"id": cid, "status": status, "evidence": ev})
    report = {"run": os.path.abspath(a.run), "profile": prof.get("name", ""),
              "ok": not any(x["status"] == "fail" for x in out), "invariants": out}
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
