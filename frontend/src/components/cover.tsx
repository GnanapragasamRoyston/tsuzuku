/**
 * Jaquette 2:3 (DESIGN.md § 5.1). Sans image (dataset 2020, image absente ou en erreur) : rendu
 * de secours de même taille, avec le type et le titre en serif, pour que la grille ne saute pas.
 */
"use client";

import clsx from "clsx";
import Image from "next/image";
import { useState } from "react";

import { kindLabel } from "@/lib/format";
import type { MediaSummary } from "@/lib/types";

type CoverSize = "row" | "list" | "fluid";

const WIDTH: Record<CoverSize, string> = { row: "w-40", list: "w-22", fluid: "w-full" };
// Largeur réelle affichée, pour que l'optimiseur d'images serve la bonne taille.
const SIZES: Record<CoverSize, string> = {
  row: "160px",
  list: "88px",
  fluid: "(min-width: 1024px) 400px, 50vw",
};

interface CoverProps {
  media: Pick<MediaSummary, "title" | "kind" | "cover_url">;
  size?: CoverSize;
  /** Chargement immédiat (au-dessus de la ligne de flottaison ; « priority » est déprécié en
   *  Next 16). */
  eager?: boolean;
  className?: string;
}

export function Cover({ media, size = "fluid", eager = false, className }: CoverProps) {
  const [failed, setFailed] = useState(false);
  const showImage = Boolean(media.cover_url) && !failed;
  return (
    <div
      className={clsx(
        "relative aspect-2/3 shrink-0 overflow-hidden rounded-md border border-line bg-surface",
        WIDTH[size],
        className,
      )}
    >
      {showImage ? (
        <Image
          src={media.cover_url as string}
          // Décorative : le titre est toujours écrit à côté (sinon il serait lu deux fois).
          alt=""
          fill
          sizes={SIZES[size]}
          loading={eager ? "eager" : "lazy"}
          className="object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <div
          aria-hidden="true"
          className={clsx(
            "flex h-full flex-col justify-between",
            size === "list" ? "p-2" : "p-3",
          )}
        >
          <span className="text-meta font-semibold tracking-meta text-ink-2 uppercase">
            {kindLabel(media.kind)}
          </span>
          <span
            className={clsx(
              "line-clamp-3 font-display font-semibold text-ink",
              size === "list" ? "text-small" : "text-h3",
            )}
          >
            {media.title}
          </span>
        </div>
      )}
    </div>
  );
}
