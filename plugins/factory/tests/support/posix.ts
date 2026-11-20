// The test engine's file fake keys files by POSIX paths ("/repo/.factory/x"). On Windows the engine hands the
// hooks the same file as "C:\repo\.factory\x" (mixed, "C:\repo/.factory/x", or with the "\\?\" prefix), so
// every path goes through here first: the extended-length prefix and a leading drive letter go, backslashes
// become "/". A POSIX path comes back unchanged.
export const posix = (p: string): string => p.replace(/^\\\\\?\\/, '').replace(/^[A-Za-z]:/, '').split('\\').join('/')
