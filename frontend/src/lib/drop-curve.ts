/**
 * Données de la courbe de drop (DESIGN.md § 5.5), sans rendu : testable seule.
 *
 * L'API ne renvoie que les épisodes où il y a eu des drops (mart.drop_curve) ; la courbe montre
 * pourtant chaque épisode, trous compris, sinon un creux serait invisible. Au-delà de 26 épisodes,
 * regroupement par tranches (5 épisodes au moins) pour rester lisible sur mobile. L'épisode 0 (« avant de
 * commencer ») reste toujours seul : c'est un comportement à part (on lâche avant d'essayer).
 */
import { formatPercent } from "@/lib/format";

export const MAX_SINGLE_BARS = 26;
const BUCKET = 5;

export type Marker = "critical" | "ponr" | null;

export interface CurveBar {
  label: string;
  from: number;
  to: number;
  drops: number;
  /** Part de tous les drops de l'œuvre tombés dans cette barre (0 à 1). */
  share: number;
  marker: Marker;
}

interface CurveContext {
  episodes: number | null;
  critical: number | null;
  pointOfNoReturn: number | null;
}

export function curveBars(
  points: { episode: number; nb_drops: number }[],
  { episodes, critical, pointOfNoReturn }: CurveContext,
): CurveBar[] {
  if (points.length === 0) return [];
  const last = Math.max(episodes ?? 0, ...points.map((p) => p.episode));
  const total = points.reduce((sum, p) => sum + p.nb_drops, 0);
  const grouped = last > MAX_SINGLE_BARS;
  // Tranches de 5 au moins, plus larges pour les séries très longues (500 épisodes → 20) : jamais
  // plus de 26 barres, sinon elles ne tiennent plus en largeur sur mobile (revue de la phase 9).
  const size = grouped ? Math.max(BUCKET, Math.ceil(last / MAX_SINGLE_BARS)) : 1;

  const ranges: [number, number][] = [];
  if (points.some((p) => p.episode === 0)) ranges.push([0, 0]);
  for (let start = 1; start <= last; start += size) {
    ranges.push([start, Math.min(last, start + size - 1)]);
  }

  const within = (value: number | null, from: number, to: number) =>
    value !== null && value >= from && value <= to;
  return ranges.map(([from, to]) => {
    const drops = points
      .filter((p) => p.episode >= from && p.episode <= to)
      .reduce((sum, p) => sum + p.nb_drops, 0);
    // Les deux repères dans la même tranche : le critique (l'alerte) l'emporte.
    const marker: Marker = within(critical, from, to)
      ? "critical"
      : within(pointOfNoReturn, from, to)
        ? "ponr"
        : null;
    return {
      label: from === to ? String(from) : `${from}–${to}`,
      from,
      to,
      drops,
      share: total > 0 ? drops / total : 0,
      marker,
    };
  });
}

export function curveSummary({
  critical,
  criticalShare,
  pointOfNoReturn,
}: {
  critical: number;
  criticalShare: number;
  pointOfNoReturn: number | null;
}): string {
  const parts = [
    "Courbe de drop par épisode.",
    `Épisode critique : ${critical}, avec ${formatPercent(criticalShare, 0)} des drops.`,
  ];
  if (pointOfNoReturn !== null) parts.push(`Point de non-retour : épisode ${pointOfNoReturn}.`);
  return parts.join(" ");
}
