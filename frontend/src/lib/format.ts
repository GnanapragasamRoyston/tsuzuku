/**
 * Formats français (DESIGN.md § 2.2) : toujours Intl, jamais à la main. Intl fr-FR place des
 * espaces fines insécables (milliers, avant %) : un nombre ne se coupe jamais en fin de ligne.
 */
import type { Kind, MediaSummary } from "@/lib/types";

const INT = new Intl.NumberFormat("fr-FR");

export function formatInt(n: number): string {
  return INT.format(n);
}

export function formatPercent(share: number, digits = 1): string {
  return new Intl.NumberFormat("fr-FR", {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(share);
}

const KIND_LABEL: Record<Kind, string> = {
  anime: "Anime",
  manga: "Manga",
  manhwa: "Manhwa",
  manhua: "Manhua",
};

export function kindLabel(kind: Kind): string {
  return KIND_LABEL[kind];
}

const FORMAT_LABEL: Record<string, string> = { Movie: "Film", Music: "Clip", Special: "Spécial" };

type MetaSource = Pick<MediaSummary, "kind" | "format" | "episodes" | "chapters" | "start_year">;

/** « TV · 12 ép. · 2014 » pour un anime, « Manhwa · 201 chap. · 2018 » sinon. */
export function mediaMeta(m: MetaSource): string {
  const parts: string[] = [];
  if (m.kind === "anime") {
    if (m.format) parts.push(FORMAT_LABEL[m.format] ?? m.format);
    if (m.episodes) parts.push(`${formatInt(m.episodes)} ép.`);
  } else {
    parts.push(kindLabel(m.kind));
    parts.push(m.chapters ? `${formatInt(m.chapters)} chap.` : "en cours");
  }
  if (m.start_year) parts.push(String(m.start_year));
  return parts.join(" · ");
}
