/** Sélection de l'onboarding : au moins N œuvres aimées (settings.yaml, 10 ; SPEC § 8). */

/**
 * Minimum d'œuvres, recopié de config/settings.yaml (api.onboarding_min_choices). L'API reste
 * juge : si les deux divergent, elle répond 422 avec le bon minimum, affiché tel quel.
 */
export const ONBOARDING_MIN = 10;

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
