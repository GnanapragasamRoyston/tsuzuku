/**
 * En-têtes du relais de confiance (phase 11, ADR 014), ajoutés par proxy.ts aux requêtes /api/*
 * relayées vers l'API.
 *
 * - X-Tsuzuku-Proxy : secret partagé avec l'API ; sans lui, l'API répond 403. Il n'existe que
 *   côté serveur (variable PROXY_SECRET, jamais NEXT_PUBLIC_) : le navigateur ne le voit pas.
 * - X-Tsuzuku-Client-IP : IP du visiteur, pour la limite de connexion par IP. Seulement sur
 *   Vercel, où x-forwarded-for est posé par la plateforme ; ailleurs, cet en-tête vient du
 *   client et se falsifie : rien n'est transmis.
 * Les valeurs envoyées par le client pour ces deux en-têtes sont toujours écrasées ou retirées.
 */

const SECRET_HEADER = "x-tsuzuku-proxy";
const CLIENT_IP_HEADER = "x-tsuzuku-client-ip";

export function proxyHeaders(
  incoming: Headers,
  { secret, onVercel }: { secret: string | undefined; onVercel: boolean },
): Headers | null {
  if (!secret) return null;
  const headers = new Headers(incoming);
  headers.set(SECRET_HEADER, secret);
  headers.delete(CLIENT_IP_HEADER);
  const ip = onVercel ? incoming.get("x-forwarded-for")?.split(",")[0]?.trim() : undefined;
  if (ip) headers.set(CLIENT_IP_HEADER, ip);
  return headers;
}

/** Pour les appels faits par le serveur Next lui-même (pages rendues côté serveur). */
export function serverProxyHeader(): Record<string, string> {
  const secret = process.env.PROXY_SECRET;
  return secret ? { [SECRET_HEADER]: secret } : {};
}
