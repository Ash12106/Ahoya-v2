import { NextRequest, NextResponse } from "next/server";

import { forwardJson, invalidJsonResponse, originIsAllowed, readLimitedJsonBody } from "@/lib/bff";

export const runtime = "nodejs";

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!originIsAllowed(request)) {
    return NextResponse.json(
      { code: "FORBIDDEN", message: "Request forbidden" },
      { status: 403, headers: { "Cache-Control": "private, no-store" } },
    );
  }
  const body = await readLimitedJsonBody(request);
  if (body === null) return invalidJsonResponse(413);
  try {
    JSON.parse(body);
  } catch {
    return invalidJsonResponse();
  }
  return forwardJson(request, "/v1/consents", "POST", body);
}
