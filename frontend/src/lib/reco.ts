/**
 * Phrase sous « Pour toi » (ton de DESIGN.md § 7). Recomposée ici plutôt que de reprendre la
 * raison de l'API, écrite pour les développeurs (« 10 anime(s) aimé(s) »).
 */
import type { RecoResponse } from "@/lib/types";

/** « anime » : recos ALS ; « books » : mangas, manhwas et manhuas (par le contenu, phase 10). */
export type RecoShelf = "anime" | "books";

export function recoReason(
  { strategy, liked_used }: Pick<RecoResponse, "strategy" | "liked_used">,
  shelf: RecoShelf = "anime",
): string {
  if (strategy === "popularity") {
    return shelf === "books"
      ? "Les plus lus, le temps d'en savoir plus sur tes goûts."
      : "Les animes les plus suivis, le temps d'en savoir plus sur tes goûts.";
  }
  if (strategy === "content") {
    return liked_used === 1
      ? "Proches de l'histoire et du ton de l'œuvre que tu as aimée."
      : `Proches de l'histoire et du ton des ${liked_used} œuvres que tu as aimées.`;
  }
  return liked_used === 1
    ? "Calculé à partir de l'anime que tu as aimé."
    : `Calculé à partir des ${liked_used} animes que tu as aimés.`;
}
