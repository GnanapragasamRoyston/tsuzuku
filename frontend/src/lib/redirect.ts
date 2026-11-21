/**
 * Retour après connexion (?suivant=/ma-liste). Seuls les chemins INTERNES sont acceptés : sinon
 * un lien piégé (?suivant=https://site-pirate) renverrait la personne, juste connectée, ailleurs
 * (redirection ouverte, OWASP).
 *
 * On valide APRÈS analyse de l'URL, comme le fera le navigateur : il retire tabulations et sauts
 * de ligne (« /\t/hote » devient « //hote », un autre site), et lit « \ » comme « / ».
 */
const INTERNAL = "http://interne.invalid";

export function safeNext(value: string | null, fallback: string): string {
  // Caractères de contrôle et antislash : refusés d'emblée (jamais utiles dans nos chemins).
  if (!value || !value.startsWith("/") || /[\u0000-\u001F\u007F\\]/.test(value)) return fallback;
  try {
    const url = new URL(value, INTERNAL);
    if (url.origin !== INTERNAL) return fallback;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return fallback;
  }
}
