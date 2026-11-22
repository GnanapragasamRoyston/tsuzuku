/**
 * Courbe de drop par épisode (DESIGN.md § 5.5) : barres CSS, sans bibliothèque de graphes (le
 * besoin tient en une rangée de barres ; une bibliothèque ajouterait du JavaScript au navigateur
 * pour rien). Rendu serveur, aucun état.
 *
 * Accessibilité : la zone graphique est une image (role="img") résumée par son aria-label, et un
 * tableau équivalent masqué visuellement donne toutes les valeurs.
 */
import clsx from "clsx";

import { curveBars, curveSummary, type Marker } from "@/lib/drop-curve";
import { formatPercent } from "@/lib/format";
import type { MediaDetail } from "@/lib/types";

const BAR_COLOR: Record<Exclude<Marker, null> | "none", string> = {
  critical: "bg-accent",
  ponr: "bg-good",
  none: "bg-chart",
};

// Au-delà, les valeurs écrites au-dessus des barres se chevaucheraient : elles passent au survol,
// comme sur mobile (adaptation notée dans DESIGN.md § 5.5).
const MAX_WRITTEN_VALUES = 13;

export function DropCurve({ media }: { media: MediaDetail }) {
  const critical = media.critical;
  if (!critical || media.drop_curve.length === 0) {
    return (
      <p className="text-ink-2">
        Pas de courbe pour cette œuvre : elle n&apos;a pas d&apos;historique de drops dans les
        données MyAnimeList 2020. On ne va pas inventer un chiffre.
      </p>
    );
  }
  const bars = curveBars(media.drop_curve, {
    episodes: media.episodes,
    critical: critical.critical_episode,
    pointOfNoReturn: critical.point_of_no_return,
  });
  const peak = Math.max(...bars.map((b) => b.share));
  const writeValues = bars.length <= MAX_WRITTEN_VALUES;

  return (
    <figure className="flex flex-col gap-4">
      <div
        role="img"
        aria-label={curveSummary({
          critical: critical.critical_episode,
          criticalShare: critical.critical_drop_share,
          pointOfNoReturn: critical.point_of_no_return,
        })}
        className="flex h-40 items-end gap-1 border-b border-ink pt-6"
      >
        {bars.map((bar) => (
          <div key={bar.label} className="group relative flex h-full flex-1 items-end">
            <div
              className={clsx("w-full", BAR_COLOR[bar.marker ?? "none"])}
              // Hauteur relative au pic : la barre la plus haute remplit la zone.
              style={{ height: peak > 0 ? `${(bar.share / peak) * 100}%` : "0%" }}
            />
            {bar.share > 0 && (
              <span
                className={clsx(
                  "absolute inset-x-0 text-center text-meta tabular-nums text-ink-2",
                  writeValues ? "hidden md:block" : "hidden group-hover:block",
                )}
                style={{ bottom: `calc(${(bar.share / peak) * 100}% + 4px)` }}
              >
                {formatPercent(bar.share, 0)}
              </span>
            )}
          </div>
        ))}
      </div>
      <div aria-hidden="true" className="flex justify-between text-meta tabular-nums text-ink-2">
        <span>Ép. {bars[0].label}</span>
        <span>Ép. {bars.at(-1)?.label}</span>
      </div>

      <figcaption className="flex flex-col gap-2">
        <p className="flex items-center gap-2">
          <span aria-hidden="true" className="size-3 shrink-0 bg-accent" />
          <span>
            Épisode {critical.critical_episode} — critique.{" "}
            {formatPercent(critical.critical_drop_share, 0)} des drops tombent ici.
          </span>
        </p>
        {critical.point_of_no_return !== null && (
          <p className="flex items-center gap-2">
            <span aria-hidden="true" className="size-3 shrink-0 bg-good" />
            <span>Épisode {critical.point_of_no_return} — point de non-retour.</span>
          </p>
        )}
        <p className="text-small text-ink-2">Données MyAnimeList 2020.</p>
      </figcaption>

      <table className="sr-only">
        <caption>Part des drops par épisode</caption>
        <thead>
          <tr>
            <th scope="col">Épisode</th>
            <th scope="col">Part des drops</th>
          </tr>
        </thead>
        <tbody>
          {bars.map((bar) => (
            <tr key={bar.label}>
              <th scope="row">{bar.label === "0" ? "Avant de commencer" : bar.label}</th>
              <td>{formatPercent(bar.share, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
