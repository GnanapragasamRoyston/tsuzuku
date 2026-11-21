/**
 * Proxy (anciennement « middleware », Next 16) : contrôle OPTIMISTE des pages de compte.
 * Sans cookie de session → page de connexion, avec retour prévu (?suivant=). La vraie
 * vérification reste côté API (jeton signé, révocation) : un cookie expiré passe ici, puis
 * l'API répond 401 et la page renvoie vers la connexion.
 */
import { type NextRequest, NextResponse } from "next/server";

// Nom du cookie posé par l'API (backend/app/core/security.py, COOKIE_NAME).
const SESSION_COOKIE = "tsuzuku_session";

export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const url = request.nextUrl.clone();
  url.pathname = "/connexion";
  url.search = `?suivant=${encodeURIComponent(request.nextUrl.pathname)}`;
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/ma-liste/:path*", "/onboarding/:path*", "/compte/:path*"],
};
