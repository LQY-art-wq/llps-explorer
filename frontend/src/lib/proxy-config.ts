/** Server-side routing helpers. The upstream address is never returned to clients. */
const HOST_AUTHORITY = /^(?:\[[0-9a-f:.]+\]|[a-z0-9.-]+)(?::[0-9]{1,5})?$/i;

/** Compare the browser origin with the actual Host, never Next's normalized URL. */
export function allowedRequestOrigin(origin: string | null, host: string | null): boolean {
  // CLI clients may omit Origin. A present but empty or opaque origin is invalid.
  if (origin === null) return true;
  const parts = /^(https?):\/\/([^/?#]+)$/i.exec(origin);
  if (!parts || !host || origin !== origin.trim() || host !== host.trim()
    || !HOST_AUTHORITY.test(parts[2]) || !HOST_AUTHORITY.test(host)) return false;
  try {
    const source = new URL(origin);
    // Use the declared scheme to normalize default ports. This also supports TLS
    // termination when the edge preserves Host; forwarded-host headers are ignored.
    const target = new URL(`${source.protocol}//${host}`);
    return source.host === target.host;
  } catch {
    return false;
  }
}

export function allowedApiPath(path: string[], method: string): boolean {
  const joined = path.join("/");
  if (method === "GET") {
    return joined === "health" || joined === "methods" ||
      joined === "config/public" || joined === "analysis" || joined === "analysis/history" ||
      /^analysis\/[A-Za-z0-9_-]{1,128}$/.test(joined) ||
      /^analysis\/[A-Za-z0-9_-]{1,128}\/export\/(json|summary\.csv|residues\.csv|regions\.csv|fasta)$/.test(joined) ||
      /^methods\/(lreca|fuzdrop|seg|dismeta)\/health$/.test(joined);
  }
  if (method === "DELETE") return /^analysis\/[A-Za-z0-9_-]{1,128}$/.test(joined);
  return method === "POST" && (joined === "analysis" || joined === "methods/fuzdrop/import");
}

export function upstreamApiUrl(configured: string | undefined, path: string[]): URL | null {
  const safeSegment = (part: string) => /^[A-Za-z0-9_-]+$/.test(part)
    || /^(summary\.csv|residues\.csv|regions\.csv)$/.test(part);
  if (!configured || path.some((part) => !safeSegment(part))) return null;
  try {
    const url = new URL(configured);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password ||
      url.search || url.hash) return null;
    url.pathname = `${url.pathname.replace(/\/$/, "")}/api/v1/${path.join("/")}`;
    return url;
  } catch {
    return null;
  }
}
