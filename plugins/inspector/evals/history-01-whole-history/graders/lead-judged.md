---
type: llm
focus: { source: file, path: docs/inspector/case.md }
weight: 3
---

PASS if the case file's open leads include app/mail.py's email_body putting the name and title into HTML unescaped, as the same bug PR #4 fixed only in html_title, with the change (html.escape). FAIL if that lead is missing, or if email_subject (plain text by the README) or the CSV export (unquoted by design, per the README) is reported as an open lead.
