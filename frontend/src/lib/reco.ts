/**
 * Phrase sous « Pour toi » (ton de DESIGN.md § 7). Recomposée ici plutôt que de reprendre la
 * raison de l'API, écrite pour les développeurs (« 10 anime(s) aimé(s) »).
 */
import type { RecoResponse } from "@/lib/types";

export function recoReason({ strategy, liked_used }: Pick<RecoResponse, "strategy" | "liked_used">): string {
  if (strategy === "popularity") {
    return "Les animes les plus suivis, le temps d'en savoir plus sur tes goûts.";
  }
  return liked_used === 1
    ? "Calculé à partir de l'anime que tu as aimé."
    : `Calculé à partir des ${liked_used} animes que tu as aimés.`;
}
