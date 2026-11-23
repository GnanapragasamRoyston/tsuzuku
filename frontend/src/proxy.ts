/**
 * Proxy (anciennement « middleware », Next 16) : contrôle OPTIMISTE des pages de compte.
 * Sans cookie de session → page de connexion, avec retour prévu (?suivant=). La vraie
 * vérification reste côté API (jeton signé, révocation) : un cookie expiré passe ici, puis
 * l'API répond 401 et la page renvoie vers la connexion.
 */
import { type NextRequest, NextResponse } from "next/server";

import { proxyHeaders } from "@/lib/client-ip";

// Nom du cookie posé par l'API (backend/app/core/security.py, COOKIE_NAME).
const SESSION_COOKIE = "tsuzuku_session";

export function proxy(request: NextRequest) {
  // Relais /api/* : en-têtes de confiance pour l'API (production, ADR 014). Ajoutés à la requête
  // relayée par la réécriture de next.config.ts ; le navigateur ne les voit jamais.
  if (request.nextUrl.pathname.startsWith("/api/")) {
    const headers = proxyHeaders(request.headers, {
      secret: process.env.PROXY_SECRET,
      onVercel: process.env.VERCEL === "1",
    });
    return headers ? NextResponse.next({ request: { headers } }) : NextResponse.next();
  }
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const url = request.nextUrl.clone();
  url.pathname = "/connexion";
  url.search = `?suivant=${encodeURIComponent(request.nextUrl.pathname)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: [
    "/ma-liste/:path*",
    "/onboarding/:path*",
    "/compte/:path*",
    "/pour-toi/:path*",
    "/api/:path*",
  ],
};
