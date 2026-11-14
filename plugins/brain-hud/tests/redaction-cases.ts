// Inputs both redactors (hooks/journal.ts redact, host_layout.py redact_secrets) must handle the same way.
// tests/brain.test.tsx imports this file and tests/skill/scripts/test_redaction_cases.py reads it as JSON
// (everything after `export default`), so a form added to one side and not the other fails a test.
// Keep the object strict JSON: double quotes, no trailing commas, no comments inside it.
export default {
  "redact": [
    [
      "export GH_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123",
      "ghp_abcdef"
    ],
    [
      "ran DB_PASSWORD=hunter3 then",
      "hunter3"
    ],
    [
      "mytool --password hunter2 run",
      "hunter2"
    ],
    [
      "curl https://u:pw@x.com/a",
      "u:pw@"
    ],
    [
      "curl -H \"Authorization: token ghx0abc123secret\" https://x",
      "ghx0abc123secret"
    ],
    [
      "curl -u alice:s3cretpass https://x",
      "s3cretpass"
    ],
    [
      "SLACK=xoxb-1234567890-abcdefghij npm test",
      "xoxb-1234567890"
    ],
    [
      "{\"password\": \"hunter2\"}",
      "hunter2"
    ],
    [
      "{'api_key': 'abc123secretvalue'}",
      "abc123secretvalue"
    ],
    [
      "psql postgres://admin:pw4db@db.internal/app",
      "pw4db"
    ],
    [
      "redis://:redispass@cache:6379",
      "redispass"
    ],
    [
      "curl -H 'Cookie: session=abc123sess' https://x",
      "abc123sess"
    ],
    [
      "Set-Cookie: sid=zzz999; Path=/",
      "zzz999"
    ],
    [
      "mysql -u root -phunter2secret db",
      "hunter2secret"
    ],
    [
      "sshpass -p s3cr3tpw ssh host",
      "s3cr3tpw"
    ],
    [
      "redis-cli -a redispw2 ping",
      "redispw2"
    ],
    [
      "NPM_AUTH=npmsecret123 npm publish",
      "npmsecret123"
    ]
  ],
  "keep": [
    "git push -u origin main",
    "sudo -u bob git checkout -- .",
    "git checkout -- auth.py",
    "git add -p src/app.py",
    "author: Alice",
    "see https://example.com/docs"
  ]
}
