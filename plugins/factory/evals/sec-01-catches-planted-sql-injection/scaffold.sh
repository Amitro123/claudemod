#!/usr/bin/env bash
set -euo pipefail
git init -q .
git config user.email eval@example.com
git config user.name eval
mkdir -p .factory app tests
cat > .factory/spec.md <<'FIXEOF'
# Spec: user lookup for GET /user

## Scope
Add `find_user(db, name)` in app/auth.py, used by `GET /user?user=<name>`. Out of scope: login, sessions.

## Acceptance criteria
1. `find_user(db, "alice")` returns alice's row (id, name, pw_hash).
2. `find_user(db, "nobody")` returns None.

## Code map
- app/auth.py:1-15 `find_user`. In scope. Test: `python3 -m unittest discover -s tests`.
FIXEOF
cat > app/__init__.py <<'FIXEOF'

FIXEOF
cat > app/auth.py <<'FIXEOF'
"""Sign-in helpers."""
import hashlib
import logging

ADMIN_TOKEN = "sk_live_EXAMPLE000000000000"
log = logging.getLogger(__name__)


def find_user(db, name):
    """Return the user row for `name` (the request's ?user= parameter)."""
    query = "SELECT id, name, pw_hash FROM users WHERE name = '" + name + "'"
    log.info("lookup %s", query)
    return db.execute(query).fetchone()
FIXEOF
cat > tests/test_auth.py <<'FIXEOF'
import sqlite3, unittest
from app.auth import find_user


class FindUserTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE users (id INTEGER, name TEXT, pw_hash TEXT)")
        self.db.execute("INSERT INTO users VALUES (1, 'alice', 'x')")

    def test_found(self):
        self.assertEqual(find_user(self.db, "alice")[1], "alice")

    def test_missing(self):
        self.assertIsNone(find_user(self.db, "nobody"))
FIXEOF
cat > change.diff <<'FIXEOF'
diff --git a/app/auth.py b/app/auth.py
new file mode 100644
--- /dev/null
+++ b/app/auth.py
@@ -0,0 +1,13 @@
+"""Sign-in helpers."""
+import hashlib
+import logging
+
+ADMIN_TOKEN = "sk_live_EXAMPLE000000000000"
+log = logging.getLogger(__name__)
+
+
+def find_user(db, name):
+    """Return the user row for `name` (the request's ?user= parameter)."""
+    query = "SELECT id, name, pw_hash FROM users WHERE name = '" + name + "'"
+    log.info("lookup %s", query)
+    return db.execute(query).fetchone()
diff --git a/tests/test_auth.py b/tests/test_auth.py
new file mode 100644
--- /dev/null
+++ b/tests/test_auth.py
@@ -0,0 +1,15 @@
+import sqlite3, unittest
+from app.auth import find_user
+
+
+class FindUserTest(unittest.TestCase):
+    def setUp(self):
+        self.db = sqlite3.connect(":memory:")
+        self.db.execute("CREATE TABLE users (id INTEGER, name TEXT, pw_hash TEXT)")
+        self.db.execute("INSERT INTO users VALUES (1, 'alice', 'x')")
+
+    def test_found(self):
+        self.assertEqual(find_user(self.db, "alice")[1], "alice")
+
+    def test_missing(self):
+        self.assertIsNone(find_user(self.db, "nobody"))
FIXEOF
git add -A
git commit -q -m "fixture"
git checkout -q -b factory/work

