# factory evals

Eval suite ל-`factory` 0.12.0. מתחת ל-`plugins/factory/evals/` יש גם 4 cases מקוריים של התוסף (`reviewer-*`, `spec-lists-every-copy`, `starts-a-run`); ה-13 האחרים הם הסוויטה הזו. תיאור ה-cases, מה לא מכוסה: [FACTORY-SUITE.md](FACTORY-SUITE.md). יומן ההרצות: [RUN-1-NOTES.md](RUN-1-NOTES.md).

## סיכום ההרצות (מ-RUN-1-NOTES.md)
- **עלות כוללת: כ-4.5 דולר** (הרצות 2a, 2b, 2c ו-3; ההרצה הראשונה עלתה 0, נכשלה על sandbox/auth).
- **ערך אמיתי של התוסף (Δ בין זרוע with ל-without) נמצא רק ב:**
  - `appr-04` (ESCALATE על אזור רגיש): 1.0 מול 0.67. כלל "האזור היקר" קיים רק ב-skill.
  - `plan-01`: 1.00 מול 0.85 (Δ 0.15). בלי התוסף נוצר task בודד "Write tests".
  - `spec-01`: 1.00 מול 0.87 (Δ 0.13), חלש: הרצה אחת, ו-`scope-judgement` נכשל ב-without בהרצה אחת ועבר בהרצה קודמת.
- **שאר ה-cases: אפקט תקרה.** `code-01`, `code-02`, `sec-01`, `sec-02`, `appr-01`, `appr-03`, `spec-02` (ו-`appr-02` אחרי תיקון grader) קיבלו 1.00 בשתי הזרועות, כלומר המודל הרגיל כבר עושה את זה והם משמשים כרצפה/בקרה, לא כהוכחת ערך.
- **cases של build לא הורצו** (`build-01`, `build-02`): צריכים `socat` ב-WSL ל-sandbox של Bash.
- **orchestration לא מכוסה**: ה-flow המלא של `/factory` (אישור תוכנית, worktree, סבבים) לא ניתן ל-eval headless; כל case בודק תפקיד אחד בנפרד.
- התוצאות מבוססות על `--runs 1`; Δ קטן (0.13-0.15) הוא אות גס בלבד.

## 1. שכבה חינמית (ללא מודל, ללא auth)
```bash
plugins/factory/evals/run-offline.sh
# שווה ל:
#   claude plugin validate plugins/factory
#   claude plugin test plugins/factory   # כולל chk-01 (9, רגילות) ו-chk-02 (4, gaps ידועים)
```
`tests/checks-known-gaps.test.ts` מתעד את הבאג האמיתי (קבצים שמדולגים בזיהוי ה-checks, ממצאים S1-S3 ב-`docs/findings/2026-10-29-factory-run-review.md`). 'claude-code/testing' אין בו `test.failing`, לכן ה-helper `gap()` הופך את התוצאה: הבדיקה ירוקה כל עוד הפער קיים, ו**נהיית אדומה כשמתקנים את הפער**; אז מעבירים אותה כבדיקה רגילה ל-`checks-detection.test.ts`. כך ה-CI (`mods.yml`) נשאר ירוק.

אין ל-`claude plugin eval` מצב dry-run/validate, לכן תקינות ה-cases נבדקה ב-parsing עצמי (YAML, מפתחות, regex, scaffold).

## 2. הרצה בתשלום (מודל), case אחד או כולם
כללים: להריץ ב-WSL/Linux (`scaffold_script` עובד שם), מתוך עותק של ה-repo על דיסק Linux (לא `/mnt/c`). האימות במשתני הסביבה שאתה מגדיר; הסקריפטים לא קוראים או מדפיסים אותם.
```bash
cd plugins/factory
export ...                                   # משתני האימות שלך
evals/run-all.sh                             # כל ה-cases עם case.yaml, אחד אחד, RUNS=1, MAX_COST=1.5 לכל case
evals/run-all.sh spec-02 appr-03             # רק regressions
RUNS=3 MAX_COST=3 MODEL=<model> evals/run-all.sh
ABLATION=none evals/run-all.sh               # בלי זרוע ה-baseline (חצי עלות)
ALLOW_TOOLS="Edit Write" evals/run-all.sh    # בלי Bash (לא צריך socat); ALLOW_TOOLS=none מוריד את כל ההרשאות
KEEP_TEMP=1 evals/run-all.sh                 # שומר traces
```
כל case רץ כפקודה נפרדת:
```bash
claude plugin eval . --case 'spec-02*' --runs 1 --max-cost-usd 1.5 --ablation with-without \
  --scaffold --no-publish --trust-plugin --threshold 0.7 --json evals/results/out-spec-02.json \
  --allow-tools Bash Edit Write
```
בסוף מודפסת טבלת סיכום (WITH / W/OUT / delta / pass) מקבצי `evals/results/out-<id>.json`; הלוגים ב-`evals/results/log-<id>.txt`. `evals/results/` ב-`.gitignore` ולא נכנס ל-git.

## הערות
- `--allow-tools Bash Edit Write` נדרש ל-build-01/02 (Bash צריך sandbox עם `socat`). cases של spec כותבים `.factory/spec.md` ולכן צריכים Write (הם לא מצהירים `allowed_tools` ב-case.yaml).
- `--case` תומך רק ב-`*`. ה-ids ייחודיים לפי prefix (`spec-01`, `build-02`...).
- ה-target הוא התוסף עצמו (`.`), בלי `plugins:` ב-case.yaml; זרוע ה-baseline מריצה את אותם cases בלי התוסף.
