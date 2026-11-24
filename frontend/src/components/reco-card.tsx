/**
 * Carte de reco (aside de Ma liste, page Pour toi) : jaquette, titre-lien vers la fiche, ligne
 * « pourquoi », bouton d'ajout. Extraite de my-list.tsx en phase 9 pour servir aux deux écrans.
 */
"use client";

import clsx from "clsx";
import Link from "next/link";

import { Cover } from "@/components/cover";
import { Button } from "@/components/ui/button";
import { mediaMeta } from "@/lib/format";
import type { RecoItem } from "@/lib/types";
import { useOnline } from "@/hooks/use-online";

interface RecoCardProps {
  item: RecoItem;
  done: boolean;
  pending: boolean;
  onAdd: () => void;
  /** « featured » : la reco à la une de Pour toi, jaquette en grand (DESIGN.md § 4). */
  layout?: "row" | "featured";
}

export function RecoCard({ item: { media, because }, done, pending, onAdd, layout = "row" }: RecoCardProps) {
  const featured = layout === "featured";
  const online = useOnline();
  return (
    <div className={clsx("flex gap-4", featured && "flex-col md:flex-row md:gap-8")}>
      {featured ? (
        // Largeur portée par l'enveloppe : la jaquette « fluid » remplit sa colonne.
        <div className="w-2/3 shrink-0 md:w-1/3">
          <Cover media={media} eager />
        </div>
      ) : (
        <Cover media={media} size="list" />
      )}
      <div className="flex min-w-0 flex-col gap-1">
        <h3
          className={clsx(
            "font-semibold",
            featured && "font-display text-h2",
          )}
        >
          {/* Le titre est le lien (DESIGN.md § 5.2) ; pas de préchargement (piège de l'ADR 009). */}
          <Link href={`/oeuvre/${media.id}`} prefetch={false} className="hover:underline">
            {media.title}
          </Link>
        </h3>
        <p className="text-meta font-semibold tracking-meta text-ink-2 uppercase">
          {mediaMeta(media)}
        </p>
        {because && <p className="text-small text-ink-2">Parce que tu as aimé {because}.</p>}
        {/* Le bouton reste en place une fois l'ajout fait (aria-disabled) : le focus ne se perd
            pas, et l'annonce passe par la région aria-live de la page. Libellé « Dans ta liste »
            et non « Ajouté à Prévu » : le statut peut changer ensuite (+1 ép., lâché) et le
            bouton ne doit pas mentir (test de la phase 8). */}
        <Button
          variant="quiet"
          className="self-start"
          aria-disabled={done || undefined}
          disabled={pending || !online}
          aria-label={done ? `${media.title} : dans ta liste` : `Ajouter ${media.title} à ma liste`}
          onClick={() => {
            if (!done) onAdd();
          }}
        >
          {done ? "Dans ta liste" : "Ajouter à ma liste"}
        </Button>
      </div>
    </div>
  );
}
