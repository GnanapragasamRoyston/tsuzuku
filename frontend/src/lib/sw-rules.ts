/**
 * Règles de cache du service worker (SPEC § 8.1, ADR 015), en fonction pure : testable sans
 * navigateur, et le service worker (app/sw.ts) ne fait que traduire chaque règle en stratégie.
 *
 * Principe : on ne garde hors ligne QUE ce qui est utile hors ligne et sans risque.
 * - jamais : authentification, écritures, export RGPD, recos et risque (calculés à la demande),
 *   profils publics (un profil repassé en privé doit disparaître tout de suite) ;
 * - cache PRIVÉ, vidé à la déconnexion : « Ma liste » et le compte connecté ;
 * - catalogue public, jaquettes, fichiers statiques, pages : caches publics.
 */

export type CachePolicy = "network-only" | "private-api" | "public-api" | "image" | "static" | "page";

interface RequestInfo {
  url: URL;
  method: string;
  sameOrigin: boolean;
  destination: string;
}

const PUBLIC_API = /^\/api\/(media\/(popular|search|\d+(\/similar)?)|trending)$/;
const PRIVATE_API = /^\/api\/me(\/list(\/\d+)?)?$/;

export function cachePolicy({ url, method, sameOrigin, destination }: RequestInfo): CachePolicy | null {
  if (!sameOrigin) return null; // le service worker ne touche pas aux autres origines
  const path = url.pathname;
  if (method !== "GET") return "network-only";
  if (path.startsWith("/api/")) {
    if (PRIVATE_API.test(path)) return "private-api";
    if (PUBLIC_API.test(path)) return "public-api";
    return "network-only"; // auth, export, recos, risque, profils… : rien en cache
  }
  if (path.startsWith("/profil/")) return "network-only"; // profil repassé en privé : disparu
  if (path.startsWith("/_next/image")) return "image";
  if (path.startsWith("/_next/static/") || path.startsWith("/brand/")) return "static";
  // Pages (HTML) et données de navigation de Next (?_rsc=…) : contenu public ou générique (les
  // données du compte arrivent par /api/me*, jamais dans la page).
  if (destination === "document" || url.searchParams.has("_rsc")) return "page";
  return null;
}
