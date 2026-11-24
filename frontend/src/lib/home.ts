/**
 * Boutons du haut de l'accueil selon la session (DESIGN.md § 7). Avant, ils étaient les mêmes
 * pour tout le monde : une personne connectée voyait « J'ai déjà un compte » et « Commencer avec
 * 10 titres », et croyait avoir été déconnectée ou devoir refaire l'onboarding (bug signalé en
 * production le 2026-11-24). Une seule action principale par écran (DESIGN.md § 1.3).
 */
import { ONBOARDING_MIN, needsOnboarding } from "@/lib/onboarding";
import type { Me } from "@/lib/types";

interface Action {
  href: string;
  label: string;
}

export interface HeroActions {
  primary: Action;
  secondary: Action;
}

/** `null` = visiteur (ou session refusée). */
export function heroActions(me: Me | null): HeroActions {
  if (!me) {
    return {
      primary: { href: "/inscription", label: `Commencer avec ${ONBOARDING_MIN} titres` },
      secondary: { href: "/connexion", label: "J'ai déjà un compte" },
    };
  }
  const myList = { href: "/ma-liste", label: "Ma liste" };
  if (needsOnboarding(me)) {
    return { primary: { href: "/onboarding", label: `Choisir mes ${ONBOARDING_MIN} titres` }, secondary: myList };
  }
  return { primary: { href: "/pour-toi", label: "Voir mes recos" }, secondary: myList };
}
