export const DEFAULT_NEXT = "/playlists";

/**
 * Return `next` only when it is a same-origin relative path.
 *
 * The sign-in page redirects to this value after authentication, so anything
 * with a scheme (`javascript:`, `https://evil`), a protocol-relative prefix
 * (`//evil`, `/\evil`) or control characters (browsers strip tabs/newlines, so
 * `/\t/evil` would become `//evil`) must fall back to the default.
 */
export function safeNext(next: unknown, fallback: string = DEFAULT_NEXT): string {
  if (typeof next !== "string" || !next.startsWith("/")) return fallback;
  if (next.startsWith("//") || next.includes("\\")) return fallback;
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(next)) return fallback;
  return next;
}
