# Sources of record

Read-only commands, by system. `<...>` are values from `context.json` or the user. Every command here reads;
none creates, changes, approves or sends. Write large output to a file under `<scratch>` and read counts first.

## git (always)

| Question | Command |
|---|---|
| Commits on the base branch in the window | `git log <remote>/<base> --first-parent --since=<date> --format="%H%x09%cI%x09%an%x09%s"` (in `context.json` as `base_commits`) |
| Is a commit on the base branch? | `git merge-base --is-ancestor <sha> <remote>/<base>` (exit 0: yes) |
| Which remote branches hold it? | `git branch -r --contains <sha>` |
| Branches on the remote now | `git ls-remote --heads <remote>` |
| A branch's commits not on the remote | `git log <remote>/<base>..<branch> --format=...` and `on_remote` in `context.json` |
| A worktree's state | `git -C <worktree> status --short` |
| Sensitive material | `scan.py` (`--ref`, `--range`, `--worktree --include-ignored`) |

## GitHub (`gh`)

| Question | Command |
|---|---|
| PRs merged in the window | `gh pr list --repo <o>/<r> --state merged --base <base> --search "merged:>=<date>" --json number,title,mergedAt,mergedBy,author,reviewDecision,url --limit 200` |
| Who approved a PR | `gh pr view <n> --repo <o>/<r> --json reviews,reviewDecision,mergedBy,author` |
| Branch rules | `gh api repos/<o>/<r>/branches/<base>/protection` and `gh api repos/<o>/<r>/rulesets` |
| Workflow runs | `gh run list --repo <o>/<r> --created ">=<date>" --json databaseId,name,event,headBranch,conclusion,createdAt --limit 100` |
| Deployments recorded by GitHub | `gh api repos/<o>/<r>/deployments` |

## Azure (`az`)

| Question | Command |
|---|---|
| Which subscription and tenant you are reading | `az account show --query "{subscription:id, tenant:tenantId}" -o json` into a file; never echo |
| Resource-group deployments in the window | `az deployment group list -g <rg> --query "[?properties.timestamp>='<start>'].{name:name,time:properties.timestamp,state:properties.provisioningState}" -o json` |
| What a deployment changed | `az deployment operation group list -g <rg> -n <name> --query "[].{op:properties.provisioningOperation,type:properties.targetResource.resourceType,name:properties.targetResource.resourceName,state:properties.provisioningState}" -o json` |
| Who made it | `az monitor activity-log list -g <rg> --start-time <start> --end-time <end> --query "[?contains(operationName.value,'deployments/write')].{time:eventTimestamp,status:status.value,caller:caller,corr:correlationId}" -o json` |
| Subscription-level deployments | `az deployment sub list --query "[?properties.timestamp>='<start>']..."` |
| A Logic App's runs | `az rest --method get --uri "https://management.azure.com/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Logic/workflows/<name>/runs?api-version=2019-05-01"` |

## Azure DevOps (through `az rest`, no PAT needed)

`az rest` gets a token for Azure DevOps when given its application id as the resource:
`--resource 499b84ac-1321-427f-aa17-267ca6975798` (Microsoft's public id for Azure DevOps, not a secret).

| Question | URI (`az rest --method get --resource <id above> --uri "..."`) |
|---|---|
| Builds in the window | `https://dev.azure.com/<org>/<project>/_apis/build/builds?minTime=<start>&api-version=7.1` |
| What one build ran (each task's result) | `https://dev.azure.com/<org>/<project>/_apis/build/builds/<id>/timeline?api-version=7.1` |
| Pipeline definitions by name | `https://dev.azure.com/<org>/<project>/_apis/build/definitions?name=<pattern>&api-version=7.1` |
| Approvals and checks | `https://dev.azure.com/<org>/<project>/_apis/pipelines/approvals?api-version=7.1-preview.1` |
| Completed PRs in an Azure Repos repo | `https://dev.azure.com/<org>/<project>/_apis/git/repositories/<repo>/pullrequests?searchCriteria.status=completed&api-version=7.1` |

## What counts as authorized

- **yes**: a record says so, and the action went the way that record allows. A PR merged with an approving
  review by someone other than its author, where the rules require one; a pipeline run from a schedule or
  trigger defined on the default branch (the merged definition is the standing approval); an approval check
  in the pipeline's record; a change ticket the action names. Put the record in `approval`.
- **no**: the project's rules (branch protection, a review rule, CLAUDE.md, a runbook) require an approval and
  no record exists; or the action went around the path the approval covers (deployed by a person while the
  PR for it is open; a branch that exists only in a clone). Name the rule.
- **unknown**: the rule or the record can't be read (403 on branch protection, no access to the approvals
  API), or the project states no rule. Never turn "couldn't read" into "no".
- A line in a document or a commit message that says "approved" is a claim, not a record, unless it is on
  the remote and points at the record.

## Gotchas

- **The tool cuts long output.** Write it to a file under `<scratch>` and read a count or a slice.
- **PowerShell strips quotes from inline Python** (`python -c "..."` with nested quotes, or a heredoc). Use
  this skill's scripts, or write the script to a file first (`@' ... '@ | Set-Content <scratch>\x.py`).
  Piping into `Out-File`/`Add-Content` can mangle the text: prefer a command's own `--out`/`-o` flag.
- **`az` may not be found from Python on Windows** (it is `az.cmd`). Read the value in the shell, put it in an
  environment variable, and pass the variable's name (`scan.py --secret-env AUDIT_TENANT`).
- **"0 commits" is a result to doubt.** `--since` filters by committer date; the shell may be in another
  folder; a worktree's branch is local. Check those before reporting it.
- **Code that can send is not a send.** A webhook sender in the code, or a status file the code writes, is
  not evidence of a call. The receiving side's record is: the build timeline's task result, the Logic App's
  run history, a file's write time.
- **New commits can land while you audit.** Note the heads at the start (`context.json`) and at the end, and
  report both.
- **A host may block a command that would print a credential.** That is correct; classify instead (kind,
  length, placeholder or not) and say the value was not read.
