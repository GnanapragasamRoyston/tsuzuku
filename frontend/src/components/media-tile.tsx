/** Œuvre en rangée (accueil, onboarding) : jaquette, titre, métadonnées (DESIGN.md § 5.1). */
import { Cover } from "@/components/cover";
import { mediaMeta } from "@/lib/format";
import type { MediaSummary } from "@/lib/types";

export function MediaTile({ media, eager = false }: { media: MediaSummary; eager?: boolean }) {
  return (
    <div className="flex flex-col gap-2">
      <Cover media={media} eager={eager} />
      <p className="font-semibold leading-snug">{media.title}</p>
      <p className="text-meta font-semibold tracking-meta text-ink-2 uppercase">{mediaMeta(media)}</p>
    </div>
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
