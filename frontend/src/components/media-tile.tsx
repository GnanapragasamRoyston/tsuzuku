/** Œuvre en rangée (accueil, onboarding) : jaquette, titre, métadonnées (DESIGN.md § 5.1). */
import Link from "next/link";

import { Cover } from "@/components/cover";
import { mediaMeta } from "@/lib/format";
import type { MediaSummary } from "@/lib/types";

export function MediaTile({ media, eager = false }: { media: MediaSummary; eager?: boolean }) {
  // Tuile entière en lien (une seule cible) ; survol : bord line-strong, titre souligné (§ 5.1).
  // Pas de préchargement : une rangée de 12 tuiles déclencherait 12 rendus de fiche.
  return (
    <Link href={`/oeuvre/${media.id}`} prefetch={false} className="group flex flex-col gap-2">
      <Cover media={media} eager={eager} className="group-hover:border-line-strong" />
      <p className="font-semibold leading-snug group-hover:underline">{media.title}</p>
      <p className="text-meta font-semibold tracking-meta text-ink-2 uppercase">{mediaMeta(media)}</p>
    </Link>
  );
}

/** Squelette de chargement : même forme que le contenu, sans texte (DESIGN.md § 5). */
export function MediaTileSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-hidden="true">
      <div className="aspect-2/3 w-full rounded-md bg-surface" />
      <div className="h-4 w-3/4 rounded-sm bg-surface" />
      <div className="h-3 w-1/2 rounded-sm bg-surface" />
    </div>
  );
}
