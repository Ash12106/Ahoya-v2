import { getToken } from "next-auth/jwt";
import { NextRequest, NextResponse } from "next/server";

const maxJsonBodyBytes = 4096;

export function apiOrigin(): string | null {
  const value = process.env.API_INTERNAL_ORIGIN;
  if (!value) return null;
  try {
    const url = new URL(value);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    return url.origin;
  } catch {
    return null;
  }
}

export async function apiSessionToken(request: NextRequest): Promise<string | null> {
  if (!process.env.AUTH_SECRET) return null;
  try {
    const token = await getToken({ req: request, secret: process.env.AUTH_SECRET });
    if (
      typeof token?.apiSessionToken !== "string" ||
      !/^[A-Za-z0-9_-]{43,128}$/.test(token.apiSessionToken) ||
      typeof token.apiSessionExpiresAt !== "number" ||
      token.apiSessionExpiresAt <= Math.floor(Date.now() / 1000)
    ) {
      return null;
    }
    return token.apiSessionToken;
  } catch {
    return null;
  }
}

export function originIsAllowed(request: NextRequest): boolean {
  const expected = process.env.AUTH_URL;
  const origin = request.headers.get("origin");
  if (!expected || !origin) return false;
  try {
    return new URL(expected).origin === origin;
  } catch {
    return false;
  }
}

export async function readLimitedJsonBody(request: NextRequest): Promise<string | null> {
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > maxJsonBodyBytes)) {
    return null;
  }
  if (!request.body) return null;
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      total += result.value.byteLength;
      if (total > maxJsonBodyBytes) {
        await reader.cancel();
        return null;
      }
      chunks.push(result.value);
    }
  } finally {
    reader.releaseLock();
  }
  return Buffer.concat(chunks.map((chunk) => Buffer.from(chunk))).toString("utf8");
}

export function invalidJsonResponse(status = 400): NextResponse {
  return NextResponse.json(
    { code: "VALIDATION_ERROR", message: "Invalid request" },
    { status, headers: { "Cache-Control": "private, no-store" } },
  );
}

export async function forwardJson(
  request: NextRequest,
  path: string,
  method: "GET" | "POST" | "PATCH",
  body?: string,
): Promise<NextResponse> {
  const token = await apiSessionToken(request);
  const base = apiOrigin();
  if (!token) {
    return NextResponse.json(
      { code: "UNAUTHENTICATED", message: "Authentication required" },
      { status: 401, headers: { "Cache-Control": "private, no-store" } },
    );
  }
  if (!base) {
    return NextResponse.json(
      { code: "SERVICE_UNAVAILABLE", message: "Service temporarily unavailable" },
      { status: 503, headers: { "Cache-Control": "private, no-store" } },
    );
  }
  try {
    const upstream = await fetch(`${base}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    const data: unknown = await upstream.json().catch(() => null);
    const responseHeaders = new Headers({ "Cache-Control": "private, no-store" });
    const retryAfter = upstream.headers.get("Retry-After");
    if (retryAfter) responseHeaders.set("Retry-After", retryAfter);
    return NextResponse.json(
      data ?? { code: "SERVICE_UNAVAILABLE", message: "Service temporarily unavailable" },
      { status: upstream.status, headers: responseHeaders },
    );
  } catch {
    return NextResponse.json(
      { code: "SERVICE_UNAVAILABLE", message: "Service temporarily unavailable" },
      { status: 503, headers: { "Cache-Control": "private, no-store" } },
    );
  }
}
