# Outside-in sweep

The other sweeps start from the project's own promises (inside-out). This one starts from the
attacker's and the operator's side: what can reach the system, what the system writes, what it can
lose. It applies to any repository that ships hooks, agents, scripts or installers. Every question
yields candidates only; the verifier still grades them. Security labels follow references/labels.md
unchanged: a lead is `security` only with all four of `security_input`, `security_boundary`,
`security_sink`, `security_actor` and a refuted `security_counter`; otherwise it is `broken-flow`
or `hardening`.

Probe rules: read-only, on copies, no network, no secrets printed. A query or command is unverified
until parsed or run read-only. Expected lead fields are listed per question; every lead also needs
`where`, `what`, `level`, `reach`, `not_verified`, `impact`, `change`, `test`.

## 1. Trust boundaries

Look for: every place text from outside the trust zone (a third party, an API or vendor response,
another user or tenant, an outside PR author, a file a stranger can edit) reaches a model, a shell,
a file, a commit or rendered output (HTML, e-mail, markdown, a dashboard or chat message). Probe: grep
readers of external input (network calls, issue or PR text, files under shared folders,
environment) and follow each to its first sink. For a rendered-output sink: send or render one
payload containing markup (`<script>`, `<b>`, a link, a long line, an empty or missing optional
field) through the real or a stubbed renderer and read the produced body; reading the template is
not enough. Fields: `category: security`
only if all four are filled; `security_input` = the text, `security_boundary` = where trust ends,
`security_sink` = model, shell, file or commit at `path:line`, `security_actor` = the outsider;
`reach` = default-on or conditional.

## 2. Injection into session or agent context

Look for: text added to a session, prompt, memory, agent context or rendered output (HTML,
e-mail, markdown, a dashboard or chat message) by a hook, script, template or tool. Is it
size-limited, marked as data (not instructions), and who else can write the source? Probe: find
hook output and context-injection code (for rendered output, run the edge payload from question 1); check for a length cap, a delimiter or "data, not
instructions" wording, and the file permissions or shared location of the source. Fields:
`security_input` = the injected text, `security_boundary` = the context window, `security_sink` =
the model reading it, `security_actor` = whoever can write the source; `reach` = `conditional` on
who writes it.

## 3. Secrets and personal data in logs, memory and commits

Look for: data written to a shared or persistent place (log, memory file, transcript, state
folder, commit, report). Is it redacted before the write? Do ignore rules keep the folder out of
version control? Probe: grep write calls (append, dump, echo to file) and check the value for
tokens, paths with user names, emails; read ignore files for the output folder. Fields:
`category: security` (sink = the shared log or commit) or `hardening`; `security_actor` = whoever
can read the shared place; `reach` = default-on when the write is unconditional.

## 4. Enforcement versus text

Look for: every "never", "always", "must", "only" rule in docs, skill text, agent prompts and
comments. Is there code or a hook that enforces it, or is it prose only? Probe: list the rules,
then grep for the matching check, hook matcher, permission entry or test; none found is the lead.
Fields: `category: broken-flow` or `hardening` (`security` only when an outsider can cause the
violation), `breaks` = the rule as written, `level: read` with the grep as `probe`; `reach` =
default-on when nothing stops the violation.

## 5. Command construction

Look for: any command string assembled from a path, name, branch, title or user text (shell, `-c`,
string-joined argv, `eval`, a command written into a config or hook entry, a quoted path inside a
JSON command). Are quoting and escaping right for each shell and OS, including spaces and
metacharacters? Probe: grep string concatenation or f-strings near `run`, `exec`, `spawn`,
`system`, `bash -c`; test the quoting on a copy with a path holding a space and a quote. Fields:
`category: security` if an outsider controls the part (name, branch, file), else `broken-flow`;
`security_input` = the unescaped part, `security_sink` = the command at `path:line`.

## 6. Destructive writes

Look for: any write that overwrites or replaces an existing user file (settings, config, notes,
dotfiles). Is there a backup, an atomic replace, a merge instead of overwrite? What happens when
the existing file cannot be read or parsed: is it treated as empty and replaced? What state is left
if the write stops half way? Probe: read the write path and its except branch; run it on a copy with
a corrupt file and a read-only file. Fields: `category: broken-flow`, `impact` = what user data is
lost, `reach` = `conditional` on the read error or interruption.

## 7. Loss paths

Look for: archive, cleanup, dedupe, rotate, retry and sync code. What is dropped silently? Is an
unknown or missing value treated as done, expired or duplicate? Does a failure of one item discard
others, or leave no trace? Probe: read each such path for broad `except`, default values on
failure, size or age cutoffs, `continue` without a log; replay on a copy with one bad item. Fields:
`category: broken-flow`, `impact` = what is lost and whether it is noticed, `reach` per the trigger.

## 8. Packaging and install

Look for: the install and update commands in docs and scripts (do they run as written?), duplicate
registration of the same hook or agent (two manifests, two matchers, a symlink and a copy), and
what ships in the package (files that should not, files that are missing, generated copies out of
date). Probe: run the documented validator or a dry run on a copy, list the package contents,
grep registrations for duplicates. Fields: `category: broken-flow`, `breaks` = the install claim,
`reach` = default-on for a fresh install.

## Edge payloads

For any template, workflow or formatter that consumes external fields, a lead is `level: reproduced`
only if an edge payload was actually run through it (markup, a long value, an empty or missing
optional field) and the produced output was read. Otherwise the lead is `suspect`, with
`not_verified` naming the payload that was not run.
