import { NextRequest, NextResponse } from "next/server";
import { clearedSessionCookie } from "@/lib/session";
import { rejectCrossSite } from "@/lib/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: NextRequest): Promise<NextResponse> {
  const crossSite = rejectCrossSite(req);
  if (crossSite) return crossSite;

  const res = NextResponse.json({ ok: true });
  res.cookies.set(clearedSessionCookie());
  return res;
}
