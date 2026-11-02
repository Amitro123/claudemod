---
type: regex
pattern: '(hash|bcrypt|pbkdf2|scrypt|argon)'
target: { source: file, path: .factory/spec.md }
flags: i
weight: 2
---
