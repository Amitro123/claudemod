// Inputs both redactors (hooks/journal.ts redact, host_layout.py redact_secrets) must handle the same way.
// tests/brain.test.tsx imports this file and tests/skill/scripts/test_redaction_cases.py reads it as JSON
// (everything after `export default`), so a form added to one side and not the other fails a test.
// `redact`: [text, a secret that must be gone]; `keep`: text that comes back byte-identical; `after`: [text,
// substrings that must be gone, substrings that must stay] (issue #184's forms, shared since #195).
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
    ],
    [
      "aws configure set aws_secret_access_key abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "aws configure set --profile p aws_secret_access_key abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "aws configure set aws_secret_access_key abcd1234efgh --profile p",
      "abcd1234efgh"
    ],
    [
      "aws configure set aws_session_token abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "npm config set //registry.npmjs.org/:_authToken abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "curl https://x?key=abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "curl https://x?sig=abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "curl https://x?signature=abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "curl 'https://x?a=1&sig=abcd1234efgh'",
      "abcd1234efgh"
    ],
    [
      "curl https://x?Key=abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "curl -u alice:\"pa ss\" https://x",
      "pa ss"
    ],
    [
      "curl -u alice:\"pa ss\" https://x",
      "ss\""
    ],
    [
      "curl -u alice:\"pa ss\" https://x",
      "pa"
    ],
    [
      "curl -u \"alice:S3cr",
      "S3cr"
    ],
    [
      "curl -u 'alice:S3cr",
      "S3cr"
    ],
    [
      "curl -u \"alice:",
      "alice"
    ],
    [
      "curl -u \"alice:pa\"ss",
      "pa"
    ],
    [
      "curl -u \"alice:pa\"ss",
      "ss"
    ],
    [
      "curl -u :abcd1234efgh https://x",
      "abcd1234efgh"
    ],
    [
      "curl -u abcd1234efgh: https://x",
      "abcd1234efgh"
    ],
    [
      "curl -ualice:abcd1234efgh https://x",
      "abcd1234efgh"
    ],
    [
      "curl -u \\\"alice:abcd1234efgh\\\" https://x",
      "abcd1234efgh"
    ],
    [
      "curl --user=\"svc:abcd1234efgh\"",
      "abcd1234efgh"
    ],
    [
      "curl --user alice:abcd1234efgh https://x",
      "abcd1234efgh"
    ],
    [
      "curl -u a:abcd1234efgh;echo ok",
      "abcd1234efgh"
    ],
    [
      "{'Authorization': 'token 0123456789abcdef0123456789abcdef01234567'}",
      "0123456789abcdef0123456789abcdef01234567"
    ],
    [
      "{'authorization': \"Bearer abcd1234efgh\"}",
      "abcd1234efgh"
    ],
    [
      "\\\"Authorization\\\": \\\"token 0123456789abcdef0123456789abcdef01234567\\\"",
      "0123456789abcdef0123456789abcdef01234567"
    ],
    [
      "curl --ntlm -u DOMAIN\\user:abcd1234efgh https://x",
      "abcd1234efgh"
    ],
    [
      "aws  configure  set aws_secret_access_key abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "npm config set -g //registry.npmjs.org/:_authToken abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "npm config set --global //registry.npmjs.org/:_authToken abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "npm config set --location=user //registry.npmjs.org/:_authToken abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "aws configure set --profile=p aws_secret_access_key abcd1234efgh",
      "abcd1234efgh"
    ],
    [
      "curl -u \"alice\":\"abcd1234efgh\" https://x",
      "abcd1234efgh"
    ]
  ],
  "keep": [
    "git push -u origin main",
    "sudo -u bob git checkout -- .",
    "git checkout -- auth.py",
    "git add -p src/app.py",
    "author: Alice",
    "see https://example.com/docs",
    "sudo -u bob ls",
    "aws configure set region us-east-1",
    "npm config set registry https://registry.npmjs.org/",
    "press any key to continue",
    "set key=value pairs",
    "curl https://x?keyword=abc",
    "git show 3f2a9c1",
    "curl -u alice"
  ],
  "after": [
    [
      "npm config set -g //registry.npmjs.org/:_authToken mytokenvalue1234 && npm publish",
      [
        "mytokenvalue1234"
      ],
      [
        "npm publish"
      ]
    ],
    [
      "npm config set -g //registry.npmjs.org/:_authToken mytokenvalue1234 ; npm publish",
      [
        "mytokenvalue1234"
      ],
      [
        "npm publish"
      ]
    ],
    [
      "npm config set -g //registry.npmjs.org/:_authToken mytokenvalue1234 --registry https://r.example",
      [
        "mytokenvalue1234"
      ],
      [
        "--registry https://r.example"
      ]
    ],
    [
      "npm config set --global //registry.npmjs.org/:_authToken mytokenvalue1234 && npm publish",
      [
        "mytokenvalue1234"
      ],
      [
        "npm publish"
      ]
    ],
    [
      "npm config set --location=user //registry.npmjs.org/:_authToken mytokenvalue1234 && npm publish",
      [
        "mytokenvalue1234"
      ],
      [
        "npm publish"
      ]
    ],
    [
      "npm config set //registry.npmjs.org/:_authToken mytokenvalue1234 && npm publish",
      [
        "mytokenvalue1234"
      ],
      [
        "npm publish"
      ]
    ],
    [
      "aws configure set --profile=p aws_secret_access_key mytokenvalue1234 && aws s3 ls",
      [
        "mytokenvalue1234"
      ],
      [
        "aws s3 ls"
      ]
    ],
    [
      "aws configure set --profile p aws_secret_access_key mytokenvalue1234 && aws s3 ls",
      [
        "mytokenvalue1234"
      ],
      [
        "aws s3 ls"
      ]
    ],
    [
      "aws configure set --profile p aws_secret_access_key mytokenvalue1234 --region eu-west-1",
      [
        "mytokenvalue1234"
      ],
      [
        "--region eu-west-1"
      ]
    ],
    [
      "aws configure set -g aws_secret_access_key mytokenvalue1234 && aws s3 ls",
      [
        "mytokenvalue1234"
      ],
      [
        "aws s3 ls"
      ]
    ],
    [
      "curl -u \"alice:S3cr\nnext line stays",
      [
        "S3cr"
      ],
      [
        "next line stays"
      ]
    ],
    [
      "sudo -u\nalice:pw",
      [],
      [
        "alice:pw"
      ]
    ],
    [
      "curl -u a:pw;echo ok",
      [
        "a:pw"
      ],
      [
        "echo ok"
      ]
    ],
    [
      "curl -u a:\"p w\" https://x",
      [
        "p w"
      ],
      [
        "https://x"
      ]
    ]
  ]
}
