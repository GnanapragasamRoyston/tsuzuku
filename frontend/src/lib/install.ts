/**
 * Invitation à installer l'appli (DESIGN.md § 5.10, SPEC § 8.1), logique pure.
 * - iPhone / iPad : Safari n'a pas d'invite d'installation (pas de beforeinstallprompt) → guide
 *   manuel « Partager → Sur l'écran d'accueil ». iPadOS se présente comme un Mac : on le
 *   reconnaît à son écran tactile.
 * - Ailleurs (Android, ordinateur) : l'invite du navigateur, si elle est proposée.
 * Jamais à la première visite (après une action utile), jamais si l'appli est déjà installée,
 * et « Plus tard » la masque 14 jours.
 */

export type InstallPlatform = "ios" | "prompt";

export const SNOOZE_MS = 14 * 24 * 3600 * 1000;
export const USEFUL_ACTION_KEY = "tsuzuku-useful-action";
export const DISMISSED_KEY = "tsuzuku-install-dismissed";

export function detectPlatform(userAgent: string, maxTouchPoints: number): InstallPlatform {
  if (/iPhone|iPad|iPod/.test(userAgent)) return "ios";
  if (/Macintosh/.test(userAgent) && maxTouchPoints > 1) return "ios"; // iPadOS « bureau »
  return "prompt";
}

export function shouldOfferInstall({
  standalone,
  usefulAction,
  dismissedAt,
  now,
}: {
  standalone: boolean;
  usefulAction: boolean;
  dismissedAt: number | null;
  now: number;
}): boolean {
  if (standalone || !usefulAction) return false;
  return dismissedAt === null || now - dismissedAt >= SNOOZE_MS;
}
