#!/usr/bin/env bash
set -euo pipefail
git init -q .
git config user.email eval@example.com
git config user.name eval
mkdir -p .factory app tests
cat > .factory/spec.md <<'FIXEOF'
# Spec: user lookup for GET /user

## Scope
Add `find_user(db, name)` in app/auth.py, used by `GET /user?user=<name>`, and `token_ok(supplied)` that gates admin calls.
Add the `users` schema in app/db.py. Out of scope: login, sessions, the HTTP handler itself.

## Design
- The endpoint is public, so `find_user` returns only the public fields `id` and `name`, never the password hash.
- SQL uses bound parameters only. The admin token comes from the `ADMIN_TOKEN` environment variable, never from code.

## Acceptance criteria
1. `find_user(db, "alice")` returns `(1, "alice")` (id and name only).
2. `find_user(db, "nobody")` returns None.
3. `token_ok(supplied)` is True only when `supplied` equals `ADMIN_TOKEN`; False when it differs, when `ADMIN_TOKEN` is unset or empty, and when `supplied` is None.
4. `init_db(db)` in app/db.py creates the `users` table with `id`, `name` (unique) and `pw_hash` columns.

## Code map
- app/db.py `SCHEMA`, `init_db`. In scope.
- app/auth.py `find_user`, `token_ok`. In scope.
- tests/test_auth.py. Run: `python3 -m unittest discover -s tests`.
FIXEOF
cat > README.md <<'FIXEOF'
# Auth helpers
FIXEOF
git add -A
git commit -q -m "base: spec"
git checkout -q -b factory/work
cat > app/__init__.py <<'FIXEOF'
FIXEOF
cat > app/db.py <<'FIXEOF'
"""Database schema."""

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS users ("
    "id INTEGER PRIMARY KEY, "
    "name TEXT UNIQUE NOT NULL, "
    "pw_hash TEXT NOT NULL)"
)


def init_db(db):
    db.execute(SCHEMA)
    db.commit()
FIXEOF
cat > app/auth.py <<'FIXEOF'
"""Sign-in helpers."""
import hmac
import os


def find_user(db, name):
    """Return (id, name) for `name` (the request's ?user= parameter), or None."""
    return db.execute("SELECT id, name FROM users WHERE name = ?", (name,)).fetchone()


def token_ok(supplied):
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected or not isinstance(supplied, str):
        return False
    return hmac.compare_digest(supplied.encode(), expected.encode())
FIXEOF
cat > tests/test_auth.py <<'FIXEOF'
import os
import sqlite3
import unittest
from unittest import mock

from app.auth import find_user, token_ok
from app.db import init_db


class FindUserTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        init_db(self.db)
        self.db.execute("INSERT INTO users (name, pw_hash) VALUES (?, ?)", ("alice", "x"))

    def test_found_returns_id_and_name_only(self):
        self.assertEqual(find_user(self.db, "alice"), (1, "alice"))

    def test_missing(self):
        self.assertIsNone(find_user(self.db, "nobody"))

    def test_injection_text_is_just_a_name(self):
        self.assertIsNone(find_user(self.db, "x' OR '1'='1"))


class TokenOkTest(unittest.TestCase):
    def test_match(self):
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": "s3cret"}):
            self.assertTrue(token_ok("s3cret"))

    def test_mismatch_unset_empty_none(self):
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": "s3cret"}):
            self.assertFalse(token_ok("nope"))
            self.assertFalse(token_ok(None))
        with mock.patch.dict(os.environ, {"ADMIN_TOKEN": ""}):
            self.assertFalse(token_ok(""))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(token_ok("anything"))
FIXEOF
git add -A
git commit -q -m "add find_user, token_ok, schema"
git diff HEAD~1 HEAD > change.diff
