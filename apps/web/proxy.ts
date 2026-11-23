import { Buffer } from "node:buffer";
import { randomUUID, timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

function contentSecurityPolicy(nonce: string): string {
  const development = process.env.NODE_ENV === "development";
  const directives = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`,
    `style-src 'self'${development ? " 'unsafe-inline'" : ` 'nonce-${nonce}'`}`,
    "img-src 'self' blob: data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];

  if (process.env.NODE_ENV === "production") {
    directives.push("upgrade-insecure-requests");
  }

  return directives.join("; ");
}

function originTokenIsValid(request: NextRequest): boolean {
  const expected = process.env.CLOUDFLARE_ORIGIN_TOKEN;
  const received = request.headers.get("x-ahoya-origin-token") ?? "";
  if (!expected || Buffer.byteLength(expected, "utf8") < 32) {
    return false;
  }

  const expectedBytes = Buffer.from(expected, "utf8");
  const receivedBytes = Buffer.from(received, "utf8");
  return expectedBytes.length === receivedBytes.length && timingSafeEqual(expectedBytes, receivedBytes);
}

export function proxy(request: NextRequest): NextResponse {
  const requestId = randomUUID();

  if (
    process.env.NODE_ENV === "production" &&
    request.nextUrl.pathname !== "/health" &&
    !originTokenIsValid(request)
  ) {
    return NextResponse.json(
      { code: "ORIGIN_UNVERIFIED", message: "Request forbidden", request_id: requestId },
      {
        status: 403,
        headers: {
          "X-Request-ID": requestId,
          "X-Content-Type-Options": "nosniff",
          "X-Frame-Options": "DENY",
          "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        },
      },
    );
  }

  const nonce = Buffer.from(randomUUID()).toString("base64");
  const policy = contentSecurityPolicy(nonce);
  const requestHeaders = new Headers(request.headers);
  requestHeaders.delete("x-ahoya-origin-token");
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  requestHeaders.set("X-Request-ID", requestId);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", policy);
  response.headers.set("X-Request-ID", requestId);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
