#!/usr/bin/env python3
"""Deterministic lint for leads: catches label mistakes before a person or a verifier spends time.

    python lint_leads.py <leads.json | folder of *.json | -> [--strict]

Input: a JSON array of leads, or case cards (their `complete.siblings`), from a file, a folder or
stdin (`-`). Output, one line per finding: `<where> | <rule id> | <warn|info> | <message>`.
Exit 0 always, except `--strict` (exit 1 when any warn) and invalid input (exit 2).
Rules L1-L9: references/labels.md says what each label means.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leadsio  # noqa: E402

OWNER_ACTOR_RE = re.compile(
    r"\b(owner|maintainers?|we|our|same team|own repo(?:sitory)?|the person|the user themselves?|"
    r"administrators?|admin|anyone with dashboard access)\b", re.I)
DRIFT_RE = re.compile(
    r"format drift|drifts?\b|model output (?:varies|varying|differs)|output (?:varies|varying)|varying output|"
    r"non-?determinis|rare input|rarely|\brace\b|race condition", re.I)
BEHAVIORAL_RE = re.compile(
    r"behaviou?ral|exercis|invok|\bcalls?\b|runs? the|end-to-end|fails? on the unfixed|\bintegration\b", re.I)
BY_DESIGN_RE = re.compile(r"\b(documented|by design|intended|pinned)\b", re.I)
EXTERNAL_TOOL_RE = re.compile(r"\bflags?\b|(?<![\w-])--[a-z]|\boptions?\b|\bCLI\b", re.I)
FLAG_TOKEN_RE = re.compile(r"(?<![\w-])--[a-z][\w-]*")
QUERY_RE = re.compile(
    r"\|\s*(?:where|summarize)\b|(?-i:\bSELECT\b.+?\bFROM\b)|\bkusto\b|\baz\s+monitor\s+log-analytics\s+query\b",
    re.I | re.S)
READ_ONLY_RE = re.compile(r"read[- ]?only", re.I)
DONE_RE = re.compile(r"\b(?:ran|executed)\b", re.I)  # completed; not "run" (an instruction) or "executing"
OBSERVED_RE = re.compile(r"\b(?:returned|returns|rows?|records?|results?|count(?:ed)?|yielded|showed|output|found|empty)\b", re.I)
NEGATED_RE = re.compile(
    r"\b(?:not|never|no access|unavailable|unable|could ?n[o']t|can ?n[o']t|did ?n[o']t|was ?n[o']t|were ?n[o']t)\b|n't\b", re.I)
FUTURE_RE = re.compile(
    r"\b(?:run this|to be run|to run|to execute|after|before|should|will|must|would|needs? to|please|once|later|if|when|pending)\b", re.I)
VERIFIED_LEVELS = ("reproduced", "read")

Finding = tuple[str, str, str]  # rule id, severity, message


def text(v: object) -> str:
    if isinstance(v, (str, int, float)) and not isinstance(v, bool):
        return " ".join(str(v).split())
    return ""


def level_of(s: dict) -> str:
    v = text(s.get("level")).lower()
    return next((k for k in ("reproduced", "read", "suspect", "unverified") if v.startswith(k)), v)


def host_check(s: dict) -> bool:
    flags = s.get("flags")
    flags = [flags] if isinstance(flags, str) else flags if isinstance(flags, list) else []
    return bool(s.get("needs_host_check")) or "needs-host-check" in [str(f).strip().lower() for f in flags]


def is_security(s: dict) -> bool:
    return text(s.get("category")).lower() == "security"


def rule_l1(s: dict) -> list[Finding]:
    if not is_security(s):
        return []
    actor = text(s.get("security_actor"))
    if not actor:
        return [("L1", "warn", "category security but no security_actor; name an outsider who controls the input, or it is not security")]
    m = OWNER_ACTOR_RE.search(actor)
    if m:
        return [("L1", "warn", f"security_actor reads like an owner ('{m.group(0)}'); an actor who already holds that access makes this broken-flow")]
    return []


def rule_l2(s: dict) -> list[Finding]:
    if is_security(s) and host_check(s) and level_of(s) != "reproduced" and not text(s.get("security_sink")):
        return [("L2", "warn", "security with needs-host-check and no security_sink: the consequence is not traced")]
    return []


def rule_l3(s: dict) -> list[Finding]:
    if text(s.get("reach")).lower().split(":")[0].strip() != "default-on":
        return []
    when = text(s.get("reach_when"))
    if when:
        return [("L3", "warn", f"reach default-on but reach_when is set ('{when[:40]}'); that is conditional")]
    m = DRIFT_RE.search(text(s.get("what")))
    if m:
        return [("L3", "warn", f"reach default-on but the lead mentions '{m.group(0)}'; that is conditional")]
    return []


def rule_l4(s: dict) -> list[Finding]:
    saved = s.get("probe_file")
    if level_of(s) in VERIFIED_LEVELS and not text(s.get("probe")) and not (isinstance(saved, dict) and text(saved.get("path"))):
        return [("L4", "warn", f"level {level_of(s)} but no probe; give the input and output, command, or path:line read")]
    return []


def rule_l5(s: dict) -> list[Finding]:
    if text(s.get("test_kind")).lower() == "text-pin" and not BEHAVIORAL_RE.search(text(s.get("test"))):
        return [("L5", "info", "test_kind text-pin and no behavioral test mentioned; a text pin does not fail on changed behavior")]
    return []


def rule_l6(s: dict) -> list[Finding]:
    imp = s.get("impact")
    ilvl = text(imp.get("level")).lower() if isinstance(imp, dict) else ""
    if ilvl.startswith("unverified") and level_of(s) == "reproduced" and not host_check(s):
        return [("L6", "warn", "level reproduced but impact level unverified without needs-host-check; one of them is wrong")]
    return []


def rule_l7(s: dict) -> list[Finding]:
    m = BY_DESIGN_RE.search(text(s.get("what")) + " " + text(s.get("breaks")))
    if m and not s.get("documented") and not text(s.get("reconcile")):
        return [("L7", "warn", f"'{m.group(0)}' with no documented field and no reconcile; severity cannot be set from code alone")]
    return []


def rule_l8(s: dict) -> list[Finding]:
    what, probe = text(s.get("what")), text(s.get("probe"))
    if not EXTERNAL_TOOL_RE.search(what):
        return []
    if not probe:
        return [("L8", "warn", "headline claim about an external tool or flag with no probe; run its --help or move it to not_verified")]
    tokens = FLAG_TOKEN_RE.findall(what)
    if tokens and not any(t in probe for t in tokens):
        return [("L8", "warn", f"claim names {', '.join(tokens[:3])} but the probe does not mention it")]
    return []


def rule_l9(s: dict) -> list[Finding]:
    if text(s.get("change_status")).lower() != "verified" or not QUERY_RE.search(text(s.get("change"))):
        return []
    run = s.get("query_run")
    if isinstance(run, dict):  # structured evidence: the producer says what it did and what it saw
        observed = text(run.get("observed"))
        if (text(run.get("mode")).lower() == "read-only" and text(run.get("status")).lower() == "executed"
                and observed and not NEGATED_RE.search(observed)):
            return []
    probe = text(s.get("probe"))
    if (READ_ONLY_RE.search(probe) and DONE_RE.search(probe) and OBSERVED_RE.search(probe)
            and not NEGATED_RE.search(probe) and not FUTURE_RE.search(probe)):
        return []
    return [("L9", "warn", "query inside a verified change has no evidence of a completed read-only run with an observed result (probe text or `query_run`); run it read-only or mark the change unverified")]


RULES = (rule_l1, rule_l2, rule_l3, rule_l4, rule_l5, rule_l6, rule_l7, rule_l8, rule_l9)


def lint(lead: dict) -> list[Finding]:
    return [f for r in RULES for f in r(lead)]


def load(src: str) -> list[dict]:
    return leadsio.leads_of(leadsio.read_items(src))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("leads", help="a leads JSON file, a folder of *.json, or - for stdin")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any finding is a warn")
    a = ap.parse_args(argv)
    try:
        leads = load(a.leads)
    except leadsio.LeadsError as exc:
        print(f"lint_leads.py: invalid input: {exc}", file=sys.stderr)
        return 2
    warns = 0
    for i, s in enumerate(leads):
        where = text(s.get("where")) or f"#{i + 1}"
        for rule, sev, msg in lint(s):
            warns += sev == "warn"
            print(f"{where} | {rule} | {sev} | {msg}")
    return 1 if a.strict and warns else 0


if __name__ == "__main__":
    sys.exit(main())
