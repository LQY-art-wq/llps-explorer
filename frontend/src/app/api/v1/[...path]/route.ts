import { randomBytes } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import {
  ANALYSIS_SESSION_COOKIE,
  refreshAnalysisSessionCookie,
  resolveAnalysisSessionToken,
} from "@/lib/analysis-session-cookie";
import { allowedApiPath, allowedRequestOrigin, upstreamApiUrl } from "@/lib/proxy-config";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const MAX_REQUEST_BYTES = 5 * 1024 * 1024;

function unavailable(status = 503, code = "ANALYSIS_UNAVAILABLE", message = "The analysis service is temporarily unavailable.") {
  return NextResponse.json({ detail: { code, message } }, { status, headers: { "Cache-Control": "no-store" } });
}

function browserSession(request: NextRequest): string {
  return resolveAnalysisSessionToken(
    request.cookies.get(ANALYSIS_SESSION_COOKIE)?.value,
    () => randomBytes(32).toString("base64url"),
  );
}

function attachSessionCookie(response: NextResponse, request: NextRequest, token: string) {
  return refreshAnalysisSessionCookie(response, token, request.nextUrl.protocol === "https:");
}

function isExport(path: readonly string[]): boolean {
  return path.length === 4 && path[0] === "analysis" && path[2] === "export";
}

function expectedExportMime(path: readonly string[]): string | null {
  if (!isExport(path)) return null;
  if (path[3] === "json") return "application/json";
  if (path[3].endsWith(".csv")) return "text/csv";
  return path[3] === "fasta" ? "text/plain" : null;
}

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const session = browserSession(request);
  const { path } = await context.params;
  if (!allowedApiPath(path, request.method)) {
    return attachSessionCookie(unavailable(404, "API_ROUTE_NOT_FOUND", "This API route is not available."), request, session);
  }
  const url = upstreamApiUrl(process.env.BACKEND_URL, path);
  if (!url) return attachSessionCookie(unavailable(), request, session);
  url.search = request.nextUrl.search;
  let body: Uint8Array | undefined;
  if (request.method === "POST" || request.method === "DELETE") {
    if (!allowedRequestOrigin(request.headers.get("origin"), request.headers.get("host"))) {
      return attachSessionCookie(unavailable(403, "INVALID_REQUEST_ORIGIN", "Submit the request from this workspace."), request, session);
    }
  }
  if (request.method === "POST") {
    if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
      return attachSessionCookie(unavailable(415, "INVALID_CONTENT_TYPE", "The request must contain JSON data."), request, session);
    }
    const reader = request.body?.getReader();
    if (!reader) return attachSessionCookie(unavailable(422, "INVALID_ANALYSIS_REQUEST", "The request body is missing."), request, session);
    const chunks: Uint8Array[] = [];
    let length = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > MAX_REQUEST_BYTES) {
          await reader.cancel();
          return attachSessionCookie(unavailable(413, "REQUEST_TOO_LARGE", "The request exceeds the 5 MiB upload limit."), request, session);
        }
        chunks.push(value);
      }
    } catch {
      return attachSessionCookie(unavailable(400, "INVALID_ANALYSIS_REQUEST", "The request could not be read."), request, session);
    } finally { reader.releaseLock(); }
    body = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  }
  try {
    const upstream = await fetch(url, {
      method: request.method,
      headers: {
        Accept: request.headers.get("accept") ?? "application/json",
        "X-Analysis-Session": session,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? Buffer.from(body) : undefined,
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(45_000)]),
    });
    const contentType = upstream.headers.get("content-type") ?? "";
    if (upstream.status !== 204 && !contentType) return attachSessionCookie(unavailable(), request, session);
    if (!upstream.ok && !contentType.toLowerCase().includes("application/json")) {
      return attachSessionCookie(unavailable(), request, session);
    }
    if (upstream.ok && !isExport(path) && upstream.status !== 204
      && !contentType.toLowerCase().includes("application/json")) {
      return attachSessionCookie(unavailable(), request, session);
    }
    const exportMime = expectedExportMime(path);
    if (upstream.ok && exportMime && !contentType.toLowerCase().startsWith(exportMime)) {
      return attachSessionCookie(unavailable(), request, session);
    }
    const headers = new Headers({ "Cache-Control": "no-store" });
    headers.set("X-Content-Type-Options", "nosniff");
    if (contentType) headers.set("Content-Type", contentType);
    const disposition = upstream.headers.get("content-disposition");
    if (isExport(path) && disposition && /^attachment(?:;|$)/i.test(disposition.trim())) {
      headers.set("Content-Disposition", disposition);
    }
    const response = new NextResponse(upstream.status === 204 ? null : upstream.body, {
      status: upstream.status,
      headers,
    });
    return attachSessionCookie(response, request, session);
  } catch {
    return attachSessionCookie(unavailable(), request, session);
  }
}

export const GET = forward;
export const POST = forward;
export const DELETE = forward;
