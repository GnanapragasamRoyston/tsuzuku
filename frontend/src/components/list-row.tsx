/**
 * Ligne de « Ma liste » (DESIGN.md § 5.2) : jaquette 88 px, titre, progression (compteur
 * modifiable + barre glissable, components/progress-control.tsx), actions « +1 ép. » et
 * « J'ai lâché ». La ligne entière n'est pas cliquable.
 */
"use client";

import Link from "next/link";

import { Cover } from "@/components/cover";
import { ProgressControl } from "@/components/progress-control";
import { Button } from "@/components/ui/button";
import { mediaMeta } from "@/lib/format";
import { canPlusOne, totalUnits, unitLabel } from "@/lib/progress";
import type { ListEntry } from "@/lib/types";
import { useOnline } from "@/hooks/use-online";

interface ListRowProps {
  entry: ListEntry;
  busy: boolean;
  onPlusOne: () => void;
  onDrop: () => void;
  onSetProgress: (value: number) => void;
}

export function ListRow({ entry, busy, onPlusOne, onDrop, onSetProgress }: ListRowProps) {
  const { media } = entry;
  const online = useOnline();
  const active = entry.status === "in_progress" || entry.status === "planning";
  const total = totalUnits(media);
  const last = total !== null && entry.progress + 1 >= total;
  const unit = unitLabel(media);
  return (
    // Actions SOUS la progression : toutes les barres ont la même largeur d'une ligne à l'autre
    // (structure constante d'un écran stable, DESIGN.md § 4).
    <li className="flex items-start gap-4 border-b border-line py-4 transition-colors duration-150 hover:bg-hover md:px-4">
      <Cover media={media} size="list" />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <h3 className="font-display text-h3 font-semibold">
          {/* Le titre est le lien vers la fiche ; la ligne entière ne l'est pas (§ 5.2). */}
          <Link href={`/oeuvre/${media.id}`} prefetch={false} className="hover:underline">
            {media.title}
          </Link>
        </h3>
        <p className="text-meta font-semibold tracking-meta text-ink-2 uppercase">
          {mediaMeta(media)}
        </p>
        <ProgressControl
          entry={entry}
          editable={active}
          disabled={!online}
          busy={busy}
          onCommit={onSetProgress}
        />
      {active && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {canPlusOne(entry) && (
            <Button
              onClick={onPlusOne}
              disabled={busy || !online}
              aria-label={
                last
                  ? `Marquer ${media.title} comme terminé`
                  : `${media.title} : +1 ${unit === "ép." ? "épisode" : "chapitre"}`
              }
            >
              {last ? "Marquer comme terminé" : `+1 ${unit}`}
            </Button>
          )}
          <Button
            variant="quiet"
            onClick={onDrop}
            disabled={busy || !online}
            aria-label={`J'ai lâché ${media.title}`}
          >
            J&apos;ai lâché
          </Button>
        </div>
      )}
      </div>
    </li>
  );
}
