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
    start = page * size
    return items[start:start + size]
FIXEOF
cat > tests/test_utils.py <<'FIXEOF'
import unittest
from app.utils import paginate


class PaginateTest(unittest.TestCase):
    def test_second_page(self):
        self.assertEqual(paginate(list(range(10)), 2, 3), [6, 7, 8])
FIXEOF
cat > change.diff <<'FIXEOF'
diff --git a/app/utils.py b/app/utils.py
new file mode 100644
--- /dev/null
+++ b/app/utils.py
@@ -0,0 +1,7 @@
+"""Small helpers."""
+
+
+def paginate(items, page, size):
+    """Return one page of items. Pages are 1-based."""
+    start = page * size
+    return items[start:start + size]
diff --git a/tests/test_utils.py b/tests/test_utils.py
new file mode 100644
--- /dev/null
+++ b/tests/test_utils.py
@@ -0,0 +1,7 @@
+import unittest
+from app.utils import paginate
+
+
+class PaginateTest(unittest.TestCase):
+    def test_second_page(self):
+        self.assertEqual(paginate(list(range(10)), 2, 3), [6, 7, 8])
FIXEOF
git add -A
git commit -q -m "fixture"
git checkout -q -b factory/work

