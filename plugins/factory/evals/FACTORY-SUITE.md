# FACTORY-SUITE: eval suite לתוסף factory (v0.12.0, חי ב-`plugins/factory/evals/`, רץ מול התוסף עצמו)

המטרה: למדוד (א) האם ה-skills של התפקידים (spec-writer, builder, security-reviewer, code-reviewer, approver) משפרים תוצאה לעומת הרצה בלי התוסף, (ב) האם התוסף "עובד" ברמת השלבים, ו-(ג) האם ה-findings מהריצה האמיתית (`docs/findings/2026-10-29-factory-run-review.md`) חוזרים.
הסוויטה נבנתה ונבדקה סטטית; תוצאות ההרצות בתשלום (עד כה) ב-[RUN-1-NOTES.md](RUN-1-NOTES.md) ובסיכום ב-[README.md](README.md).

## למה כל שלב נבדק בנפרד
`/factory` מחייב אישור תוכנית (`ui.ask`) ש-`claude -p` לא יכול לענות עליו, ולכן ה-flow המלא לא ניתן ל-eval. כל case מזריק לתפקיד אחד את הקלט שה-flow היה נותן לו: prompt בנוסח `specPrompt` / `buildPrompt` / `reviewPrompt` / `approvePrompt` מ-`hooks/flow.ts`, בתוספת repo קטן שנבנה ב-`scaffold.sh`. ה-skill נטען דרך `Skill` ("use the factory X skill"), כמו ב-evals של התוסף עצמו. המבקרים מקבלים diff מוכן ב-`change.diff` (אין להם shell).

## מבנה
```
plugins/factory/
  evals/<id>/{case.yaml,prompt.md,scaffold.sh,graders/*.md}   13 cases של הסוויטה (ליד 4 ה-cases המקוריים), ה-target הוא התוסף עצמו
  evals/run-all.sh  run-offline.sh  FACTORY-SUITE.md  RUN-1-NOTES.md  README.md
  tests/checks-detection.test.ts      chk-01, רץ ב-`claude plugin test plugins/factory`
  tests/checks-known-gaps.test.ts     chk-02, gaps ידועים: כל בדיקה קובעת את ההתנהגות של היום, ונהיית אדומה בשורה שתיקון משנה
  tests/support/checks-repo.ts        helper (לא קובץ בדיקה)
```

## ה-cases

arm: **A** = ablation with/without, ההשוואה היא הנקודה (Δ צפוי חיובי; ה-skill הוא הגורם). **P** = pass/fail רגיל (baseline צפוי להצליח גם בלי התוסף, ה-case הוא רצפה/בקרת false-positive). `skill-fired` הוא אינדיקטור with-only ולא נכנס לציון.

| id | שלב / skill | קלט | "טוב" = | graders (סוג) | מקור / למה | arm |
|---|---|---|---|---|---|---|
| spec-01-testable-criteria-no-invented-scope | spec-writer | "הוסף `--json` ל-`list`", repo shop עם roadmap בפיתוי ב-README | קריטריונים ממוספרים וניתנים להרצה, שם `src/shop/cli.py`, Out of scope + Code map, SIZE small, בלי CSV/pagination/accounts | regex על קובץ ה-spec ועל התשובה (9), llm עם rubric על scope (1) | איכות spec; "לא ממציא scope" | A (Code map ו-Out of scope באים מה-skill/prompt; הקריטריונים והסקופ משותפים) |
| plan-01-large-feature-sizing-and-tasks | spec-writer, חלק התוכנית | "הוסף חשבונות משתמש עם סיסמה" | SIZE large, 3-8 tasks, אין task בודד "write tests", סיסמאות ב-hash, Open questions | regex (6), llm (1) | plan sanity; `parseSize`/`parseTasks` | A |
| spec-02-regress-L1-generated-files | spec-writer | CLAUDE.md: `plugins/` נוצר ע"י `tools/build_plugin.py`; שינוי טקסט ב-template | ה-spec עובר דרך `src/greeter/templates/hello.txt` + המחולל + `--check`, לא עריכת היד | regex (4), llm (1) | **regression L1** (hand-edit של generated; ה-CLAUDE.md לא הגיע לתפקידים) | A |
| build-01-implements-to-spec-and-tests | builder | spec מאושר + repo; open question על פורמט price | מממש `--json`, מרחיב tests, מריץ unittest, עושה commit, לא נוגע ב-spec ולא ב-legacy, מדווח איך הכריע את ה-open question | regex על קבצים/trace (6), tool_used (4), llm (1) | builder לפי תוכנית; D3 | A חלקית (summary של open question מה-prompt+skill; הקוד עצמו P) |
| build-02-stays-in-scope-and-skips-large-files | builder | spec לשינוי `round_price` בלבד; ב-repo קבצי LEGACY, `catalog_fixture.json`, `poetry.lock` | משנה רק `money.py` ואת הבדיקה, לא קורא את הקבצים הגדולים, מריץ tests | regex (4), tool_used (5, כולל max 0) | "stays within caps" כפי שהוא ב-skill: scope + אסור לקרוא קבצים גדולים (S7) | P (ה-prompt עצמו אומר את זה; בודק שהמגבלה מכובדת) |
| sec-01-catches-planted-sql-injection | security-reviewer | diff עם SQL בשרשור מ-`?user=` + token קשיח | VERDICT CHANGES, blocker/major על SQL injection ב-`app/auth.py` | regex (3), llm (1) | catch של חולשה נטועה | P (מודל גנרי כנראה תופס; ציון Δ≈0 הוא תוצאה לגיטימית) |
| sec-02-clean-diff-no-false-positive | security-reviewer | diff נקי: query פרמטרי, token מ-env, `compare_digest` | PASS, אין blocker/major | regex (3) | **בקרת false-positive** | P |
| code-01-catches-planted-off-by-one | code-reviewer | `paginate` עם `page*size` על spec של 1-based, הבדיקה היחידה מקודדת את הבאג | CHANGES, blocker/major על `utils.py`, קריטריון 1 לא מתקיים | regex (3), llm (1) | catch של באג נטוע שהטסטים לא תופסים | A (קריאת קריטריון מול קוד ובדיקות = code-reviewer skill) |
| code-02-clean-diff-no-false-positive | code-reviewer | מימוש נכון + בדיקות לכל קריטריון | PASS, אין blocker/major | regex (3) | **בקרת false-positive** ל-code-reviewer | P |
| appr-01-escalates-on-open-blocker | approver | checks עברו, code reviewer עדיין עם blocker פתוח אחרי סבב 2 | ESCALATE ושם ה-blocker | regex (3) | עקביות החלטה מול verdicts | P (כתוב ב-prompt עצמו) |
| appr-02-approves-clean-change | approver | הכול ירוק, קבצים כפי שה-spec מונה, אין open question | APPROVE | regex (3) | **בקרה** נגד approver שרק מסלים | P |
| appr-03-regress-L2-failed-tests-never-approve | approver | checks FAILED (6 נכשלו), שני ה-reviewers PASS | לא APPROVE, ESCALATE שמזכיר את הכשל | regex (3) | **regression L2** (תוצאת הטסטים לא הגיעה לאישור) | P |
| appr-04-escalates-sensitive-area-despite-green | approver | הכול ירוק, השינוי ב-`auth.py` (login throttle) | ESCALATE עם "authentication" ב-REASON | regex (3) | כלל "אזור יקר" קיים רק ב-skill | **A, הכי נקי** (בלי ה-skill אין כלל כזה בקלט) |
| chk-01 / chk-02 (offline-mod) | `hooks/checks.ts` | `claude plugin test plugins/factory`, ללא מודל | chk-01: 9 בדיקות עוברות; chk-02: 4 gaps ידועים (כל בדיקה קובעת את ההתנהגות של היום; תיקון הופך אותה לאדומה בשורה שהשתנתה) | assertions ב-TS | תלונת "not generic enough, skipped files": S1, S2, S3, D1, S5, S6 | לא רלוונטי (קוד דטרמיניסטי) |

סה"כ: 13 cases עם מודל + 2 קבצי בדיקה offline. 6 cases הם בקרות/רגרסיות מפורשות (sec-02, code-02, appr-02 הן false-positive/over-escalation controls; spec-02 ו-appr-03 הם regressions).

### מה כל case תופס (כשל קונקרטי)
- **spec-01**: spec בלי קריטריונים בני-בדיקה ("works well"), spec שלא מונה את הקובץ, spec שמוסיף CSV/pagination מה-roadmap, SIZE=large לשינוי קטן, חסר Code map.
- **plan-01**: הערכת גודל קטנה מדי לפיצ'ר אבטחה/מודל נתונים, יותר מ-8 tasks או task "write tests" אחרון, סיסמאות בטקסט גלוי בתכנון.
- **spec-02**: spec שמורה על עריכת `plugins/...` ביד (בדיוק L1), או שלא מזכיר את המחולל וה-`--check`.
- **build-01**: builder שלא מריץ tests, לא עושה commit, כותב על ה-spec, נוגע ב-legacy, בונה roadmap, או לא מדווח איך הכריע את ה-open question.
- **build-02**: refactor של קבצי LEGACY, קריאת lockfile/fixture גדולים (עלות הקריאה), מימוש בלי ROUND_HALF_UP, בלי הרצת tests.
- **sec-01**: reviewer שמעביר SQLi כ-minor או PASS. **sec-02**: reviewer שממציא blocker על קוד נקי.
- **code-01**: reviewer שסומך על ה-test שעובר ומפספס off-by-one. **code-02**: nitpick שהופך ל-blocker/CHANGES על קוד נכון.
- **appr-01**: APPROVE למרות blocker פתוח. **appr-02**: ESCALATE תמידי (approver חסר-תועלת). **appr-03**: APPROVE כשהטסטים נכשלו. **appr-04**: APPROVE על שינוי authentication.
- **chk-01**: רגרסיה בזיהוי checks (python עמוק, nested עם touched, NOTHING_RAN, allowlist, אזהרת caps, קובץ שלא נקרא). **chk-02**: מתעדים ששלוש הפערים (S2, S3 ו-python בעומק >3) עדיין קיימים; כשיתוקנו הבדיקות יעברו.

## מה הסוויטה לא מכסה
- ה-flow המלא (`/factory`, אישור תוכנית, worktree, סבבי build-review, `Open PR`) ו-UI/pane (`art.ts`, `register.tsx`): לא ניתן headless.
- L3 (מצב "open PR" ירוק בלי PR), L4 (base לפני upstream), L5 (auto-mode classifier), L6 (worktree נשאר אחרי start שנכשל), L7 (כתיבה מחוץ ל-worktree), L8 (חיכוך עם model-router; כבר ב-combo cases), L9 (cwd של התפקידים), L12 (slug): מצבי runtime של המוד, לא ניתנים ל-eval של prompt. מועמדים לבדיקות `claude plugin test` על `flow.ts` / `register.tsx` (קיימות חלקית בתוסף: `tests/`).
- L10 (reviewer שכותב PASS ומצהיר שלא בדק): לא נמדד; כרגע ה-graders לא בודקים `NOT CHECKED`. אפשר להוסיף case אחרי שהפיצ'ר ייכנס.
- D4/D5 בצד ה-reviewer וה-spec-writer (false premise, copy שהוחמץ): כבר מכוסים ב-`evals/` של התוסף (תג `factory-roles`, 3 cases) ולא שוכפלו.
- ה-pipeline האמיתי של התפקידים משתמש ב-agents עם מודלים נקובים (sonnet/opus לפי size); כאן המודל הוא ברירת המחדל של ההרצה (`--model`), ולכן Δ הוא על ה-skill ולא על ה-routing.
- שונות: `--runs 1` נותן אות גס בלבד. לממוצע אמין יש להריץ `RUNS=3` ויותר, ובמיוחד ל-llm graders.

## ציפיות אם מריצים (לא אומתו)
- cases מסוג P צפויים לציון גבוה בשתי הזרועות; Δ קרוב לאפס אצלם אינו כשל.
- cases מסוג A (spec-01/02, plan-01, appr-04, code-01) הם אלה שיראו Δ. אם Δ=0 ב-appr-04 או spec-02, ה-skill לא תורם באותו מנגנון.
- ה-graders שמנוסחים כ-regex על `trace` (`tests-passed-in-trace`) תלויים בפורמט escape של ה-JSON ושבירים.


## sec-02: מה סוקר גרוע היה עושה (הערה, 2026-11-02)
ה-fixture נוקה אחרי RUN-1: ה-query בוחר רק `id, name` (בלי `pw_hash`), הסכמה מוגדרת ב-`app/db.py`, ה-SQL עם placeholders, הטוקן מ-env עם `compare_digest` על bytes ו-`None` נדחה, וה-spec מכסה את כל הקבצים. סוקר גרוע ייכשל ב-case כך: ימציא blocker/major מ"חשש" כללי (למשל "אין rate limit", "אין auth על ה-endpoint") שלא קשור ל-diff, או יחזיר VERDICT: CHANGES על ממצא minor. ה-graders `no-blocker-or-major`, `no-changes-verdict`, `verdict-pass` נכשלים במקרים האלה (נכשלו ב-RUN-1 על ה-fixture הישן, שבו הממצא היה לגיטימי).
