# Producer trace: leads where data is missing or stale

For a lead whose mechanism is "rows missing", "table stale" or "dashboard empty", the symptom is not the cause. Trace the producer before naming one. A guess (deleted keys, never ingested) is `suspect` at most.

## 1. Find the writer
The job or script that writes the table or file. Name it with path:line.

## 2. Read the refusal and early-exit paths before the write
Assertions, raises, `exit` codes, "skip if". Ask: does one bad record (a duplicate display name, a null, an unknown key) block the whole batch? If yes the failure is all-or-nothing, not per row.

## 3. Schedule and last successful run
Find the schedule (cron, workflow, scheduler config). Find the last successful run if observable (run history, a `max(updated_at)`, a log). If it is not observable, say so in `not_verified`.

## 4. The project's own notes
Read the mistakes, incident and runbook files that step 1 lists, for that job's name. A note about this failure may already exist.

## 5. Does anything alert
A failed or missing run: an alert, a freshness check, a visible "last updated". If nothing does, the failure is silent and that is part of the finding.

## 6. How readers join the table
Dashboards and queries that inner-join, or filter on, a table that may be stale or lack the row drop rows silently. A left join shows the gap.

Probe for each step: the line read or command run goes in the lead's `probe`.
