import { NextRequest, NextResponse } from "next/server";

import { apiOrigin, apiSessionToken } from "@/lib/bff";

export const runtime = "nodejs";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const token = await apiSessionToken(request);
  if (!token) {
    return NextResponse.json(
      { code: "UNAUTHENTICATED", message: "Authentication required" },
      { status: 401, headers: { "Cache-Control": "private, no-store" } },
    );
  }

  const base = apiOrigin();
  if (!base) {
    return NextResponse.json(
      { code: "SERVICE_UNAVAILABLE", message: "Service temporarily unavailable" },
      { status: 503, headers: { "Cache-Control": "private, no-store" } },
    );
  }

  try {
    const upstream = await fetch(`${base}/v1/account/export`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    if (!upstream.ok) {
      const data: unknown = await upstream.json().catch(() => null);
      return NextResponse.json(
        data ?? { code: "SERVICE_UNAVAILABLE", message: "Service temporarily unavailable" },
        { status: upstream.status, headers: { "Cache-Control": "private, no-store" } },
      );
    }
    if (!upstream.body) {
      return NextResponse.json(
        { code: "SERVICE_UNAVAILABLE", message: "Service temporarily unavailable" },
        { status: 503, headers: { "Cache-Control": "private, no-store" } },
      );
    }

    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: {
        "Cache-Control": "private, no-store",
        "Content-Disposition": 'attachment; filename="ahoya-account-export.json"',
        "Content-Type": "application/json; charset=utf-8",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch {
    return NextResponse.json(
      { code: "SERVICE_UNAVAILABLE", message: "Service temporarily unavailable" },
      { status: 503, headers: { "Cache-Control": "private, no-store" } },
    );
  }
}
