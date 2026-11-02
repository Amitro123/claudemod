// Helper for the offline tests: a repository as paths ("a/b.txt": text), directories implied.
import type { ChecksIO } from '../../hooks/checks'

export function repo(files: Record<string, string>): ChecksIO {
  const paths = Object.keys(files)
  return {
    async list(dir) {
      const prefix = dir.replace(/^\/r\/?/, '')
      const base = prefix ? `${prefix}/` : ''
      const seen = new Map<string, boolean>()
      for (const p of paths) {
        if (!p.startsWith(base)) continue
        const rest = p.slice(base.length)
        const slash = rest.indexOf('/')
        if (slash < 0) seen.set(rest, false)
        else seen.set(rest.slice(0, slash), true)
      }
      return [...seen].filter(([n]) => n).map(([name, isDir]) => ({ name, isDir }))
    },
    async read(path) {
      const rel = path.replace(/^\/r\//, '')
      return rel in files ? files[rel]! : null
    },
  }
}

export const pkg = (scripts: Record<string, string>) => JSON.stringify({ scripts })
export const argvs = (r: { checks: string[][] }) => r.checks.map(c => c.join(' '))
