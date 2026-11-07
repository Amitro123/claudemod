#!/usr/bin/env bash
set -euo pipefail
git init -q -b main .
git config user.email eval@example.com
git config user.name eval
git config commit.gpgsign false
git commit -q --allow-empty -m "initial"
# Merge what is in the working tree as PR #n, the way GitHub writes it.
pr() {
  git checkout -q -b "$2"; git add -A; git commit -q -m "$3"; git checkout -q main
  git merge -q --no-ff "$2" -m "Merge pull request #$1 from eval/$2" -m "$4"; git branch -q -D "$2"
}
cat > README.md <<'X'
# shop
A small shop backend. Promises:
- **User text (titles, names) is HTML-escaped wherever it becomes HTML** (pages and HTML emails).
- Email subjects are plain text.
- `total(items, discount)` is the sum of the prices, minus the discount (a fraction) once, rounded to cents.
- The CSV export is a raw dump for the shop's own scripts: values are written as they are, unquoted, and that is intended.
X
mkdir -p app
cat > app/cart.py <<'X'
def total(items, discount=0.0):
    return sum(items)
X
pr 1 cart "Add the cart total" "Add the cart total"
cat > app/pages.py <<'X'
def html_title(title):
    return f"<h1>{title}</h1>"
X
cat > app/mail.py <<'X'
def email_subject(title):
    return f"Re: {title}"


def email_body(name, title):
    return f"<p>Hi {name},</p><p>Your order {title} has shipped.</p>"
X
pr 2 render "Add page titles and order emails" "Add page titles and order emails"
cat > app/config.py <<'X'
import json


def load(path):
    with open(path) as f:
        return json.load(f)
X
pr 3 config "Add a config loader" "Add a config loader"
cat > app/pages.py <<'X'
import html


def html_title(title):
    return f"<h1>{html.escape(title)}</h1>"
X
pr 4 escape "fix: escape the title in html_title" "fix: page titles were not escaped"
cat > app/cart.py <<'X'
def total(items, discount=0.0):
    subtotal = sum(items)
    after = subtotal * (1 - discount)
    return after * (1 - discount)
X
pr 5 discount "Add discounts to the cart total" "Add discounts"
cat > app/cart.py <<'X'
def total(items, discount=0.0):
    subtotal = sum(items)
    return int(subtotal * (1 - discount))
X
pr 6 discount-twice "fix: the discount was applied twice" "fix: the discount was applied twice"
cat > app/export.py <<'X'
def to_csv(rows):
    return "\n".join(",".join(str(c) for c in r) for r in rows)
X
pr 7 csv "Add a CSV export" "Add a CSV export"
cat > app/cart.py <<'X'
def total(items, discount=0.0):
    subtotal = sum(items)
    return round(subtotal * (1 - discount), 2)
X
pr 8 cents "fix: the discounted total dropped the cents" "fix: the discounted total dropped the cents"
