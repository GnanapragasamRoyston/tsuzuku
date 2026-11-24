/** Sélection de l'onboarding : au moins N œuvres aimées (settings.yaml, 10 ; SPEC § 8). */
import type { Me } from "@/lib/types";

/**
 * Minimum d'œuvres, recopié de config/settings.yaml (api.onboarding_min_choices). L'API reste
 * juge : si les deux divergent, elle répond 422 avec le bon minimum, affiché tel quel.
 */
export const ONBOARDING_MIN = 10;

/**
 * Onboarding encore à faire : jamais fait ET liste vide. Quelqu'un qui l'a sauté mais a déjà
 * ajouté des œuvres a un profil de goûts : on ne le renvoie pas aux 10 titres.
 */
export function needsOnboarding(me: Pick<Me, "onboarding_done" | "list_size">): boolean {
  return me.list_size === 0 && !me.onboarding_done;
}

export function toggle(selected: ReadonlySet<number>, id: number): Set<number> {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}

export function counterLabel(count: number, min: number): string {
  const missing = min - count;
  if (missing <= 0) return "C'est bon : tes recos sont prêtes.";
  return `Encore ${missing} titre${missing > 1 ? "s" : ""} et tes recos sont prêtes.`;
}
