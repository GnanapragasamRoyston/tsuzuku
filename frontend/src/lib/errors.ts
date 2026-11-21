/**
 * Erreurs de l'API traduites en micro-textes (DESIGN.md § 7 : tutoiement, phrases courtes, on
 * dit ce qui se passe et ce qu'on peut faire). Jamais de détail technique affiché.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
    readonly retryAfter: number | null = null,
  ) {
    super(`API ${status}`);
    this.name = "ApiError";
  }
}

export type ErrorContext = "login" | "register" | "save" | "load";

function sentence(text: string): string {
  const trimmed = text.trim();
  const capitalized = trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  return /[.!?]$/.test(capitalized) ? capitalized : `${capitalized}.`;
}

function minutes(seconds: number | null): string {
  if (!seconds) return "quelques minutes";
  const n = Math.max(1, Math.ceil(seconds / 60));
  return n === 1 ? "1 minute" : `${n} minutes`;
}

export function messageFor(error: unknown, context: ErrorContext = "load"): string {
  if (!(error instanceof ApiError)) {
    // fetch rejeté : réseau coupé, serveur injoignable.
    return context === "save" || context === "login" || context === "register"
      ? "Impossible d'enregistrer. Vérifie ta connexion et réessaie."
      : "Impossible de charger. Vérifie ta connexion et réessaie.";
  }
  switch (error.status) {
    case 401:
      return context === "login"
        ? "Email ou mot de passe incorrect."
        : "Ta session a expiré. Reconnecte-toi.";
    case 404:
      return "Introuvable.";
    case 409:
      return context === "register"
        ? "Cet email ou ce pseudo est déjà utilisé."
        : sentence(typeof error.detail === "string" ? error.detail : "Conflit");
    case 422:
      // Nos messages d'API sont rédigés en français ; les erreurs Pydantic (liste) ne le sont pas.
      return typeof error.detail === "string"
        ? sentence(error.detail)
        : "Vérifie les champs du formulaire.";
    case 429:
      return `Trop d'essais. Réessaie dans ${minutes(error.retryAfter)}.`;
    case 503:
      return "Tsuzuku est indisponible pour le moment. Réessaie dans un instant.";
    default:
      return "Une erreur est survenue. Réessaie.";
  }
}
