#!/usr/bin/env bash
set -euo pipefail
git init -q .
git config user.email eval@example.com
git config user.name eval
mkdir -p .factory app tests
cat > .factory/spec.md <<'FIXEOF'
# Spec: paginate the order list

## Acceptance criteria
1. `paginate(items, page, size)` returns the items of one page; pages are 1-based: `paginate(list(range(10)), 1, 3) == [0, 1, 2]`.
2. The last page may be shorter: `paginate(list(range(10)), 4, 3) == [9]`.
3. A page past the end returns `[]`.
4. `page < 1` or `size < 1` raises ValueError.

## Code map
- app/utils.py:1-6 `paginate`. In scope. Tests: tests/test_utils.py. Command: `python3 -m unittest discover -s tests`.
FIXEOF
cat > app/__init__.py <<'FIXEOF'

FIXEOF
cat > app/utils.py <<'FIXEOF'
"""Small helpers."""


def paginate(items, page, size):
    """Return one page of items. Pages are 1-based."""
    if page < 1 or size < 1:
        raise ValueError("page and size must be >= 1")
    start = (page - 1) * size
    return items[start:start + size]
FIXEOF
cat > tests/test_utils.py <<'FIXEOF'
import unittest
from app.utils import paginate


class PaginateTest(unittest.TestCase):
    def setUp(self):
        self.items = list(range(10))

    def test_first_page(self):
        self.assertEqual(paginate(self.items, 1, 3), [0, 1, 2])

    def test_last_page_is_short(self):
        self.assertEqual(paginate(self.items, 4, 3), [9])

    def test_past_the_end(self):
        self.assertEqual(paginate(self.items, 5, 3), [])

    def test_bad_args(self):
        for page, size in ((0, 3), (1, 0), (-1, 3)):
            with self.assertRaises(ValueError):
                paginate(self.items, page, size)
FIXEOF
cat > change.diff <<'FIXEOF'
diff --git a/app/utils.py b/app/utils.py
new file mode 100644
--- /dev/null
+++ b/app/utils.py
@@ -0,0 +1,9 @@
+"""Small helpers."""
+
+
+def paginate(items, page, size):
+    """Return one page of items. Pages are 1-based."""
+    if page < 1 or size < 1:
+        raise ValueError("page and size must be >= 1")
+    start = (page - 1) * size
+    return items[start:start + size]
diff --git a/tests/test_utils.py b/tests/test_utils.py
new file mode 100644
--- /dev/null
+++ b/tests/test_utils.py
@@ -0,0 +1,21 @@
+import unittest
+from app.utils import paginate
+
+
+class PaginateTest(unittest.TestCase):
+    def setUp(self):
+        self.items = list(range(10))
+
+    def test_first_page(self):
+        self.assertEqual(paginate(self.items, 1, 3), [0, 1, 2])
+
+    def test_last_page_is_short(self):
+        self.assertEqual(paginate(self.items, 4, 3), [9])
+
+    def test_past_the_end(self):
+        self.assertEqual(paginate(self.items, 5, 3), [])
+
+    def test_bad_args(self):
+        for page, size in ((0, 3), (1, 0), (-1, 3)):
+            with self.assertRaises(ValueError):
+                paginate(self.items, page, size)
FIXEOF
git add -A
git commit -q -m "fixture"
git checkout -q -b factory/work

