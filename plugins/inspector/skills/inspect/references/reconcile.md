# Checks against the source of truth

When the repository has a data pipeline (a job that ingests from an external system into a table or store that dashboards read), the case file adds the section "Checks against the source of truth": one reconciliation check per pipeline. Code and history cannot show drift between the sink and the source. Agents do not run the check (no access to the production systems); it is written for a human or a later session with access, with exact steps.

## The check, one per pipeline
- **Source**: the page, API call or report a person can open, and what to read on it.
- **Sink**: the exact query on the table, ready to paste.
- **Window**: the same start and end on both sides, the same time zone, and an explicit note on partial days (today, the first and last day).
- **Aggregate**: a sum or count that does not double count across dimensions (a total taken before grouping by model, key or user).
- **Tolerance**: exact for counts; for money a stated percentage when the source rounds.

## What each outcome means
- **Match**: the ingest is accurate; look at the readers (dashboards, joins, filters) and at other jobs.
- **Low** (sink below source): look for ingest gaps by day, refused batches, missing keys.
- **High** (sink above source): look for double counting or duplicate records, overlapping windows.

## Freshness
Add one more item: the age of the newest record against the schedule (a daily job's newest record older than a day plus its run time means a missed or failed run). Give the query for the newest timestamp.

A lead about a pipeline's data may carry `reconcile`: one line naming the check.
