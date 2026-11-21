/**
 * Logique de progression de « Ma liste » (DESIGN.md § 5.2) : +1 épisode, j'ai lâché, terminé.
 *
 * PUT /me/list/{id} remplace l'entrée ENTIÈRE : chaque action part de toutes les valeurs
 * actuelles (toUpdate) pour ne jamais effacer une note ou une critique par accident.
 */
import type { ListEntry, ListEntryUpdate, MediaSummary } from "@/lib/types";

/** Épisodes (anime) ou chapitres (manga, manhwa, manhua), si le total est connu. */
export function totalUnits(media: MediaSummary): number | null {
  const total = media.kind === "anime" ? media.episodes : media.chapters;
  return total && total > 0 ? total : null;
}

export function unitLabel(media: MediaSummary): string {
  return media.kind === "anime" ? "ép." : "chap.";
}

export function toUpdate(entry: ListEntry): ListEntryUpdate {
  const { status, progress, dropped_at, score, review, started_at, finished_at } = entry;
  return { status, progress, dropped_at, score, review, started_at, finished_at };
}

export function canPlusOne(entry: ListEntry): boolean {
  const total = totalUnits(entry.media);
  return total === null || entry.progress < total;
}

export function plusOne(entry: ListEntry): ListEntryUpdate {
  const total = totalUnits(entry.media);
  const progress = total === null ? entry.progress + 1 : Math.min(total, entry.progress + 1);
  // Dernier épisode vu : terminé (l'API remet alors la progression au total).
  const status = total !== null && progress >= total ? "completed" : "in_progress";
  return { ...toUpdate(entry), status, progress, dropped_at: null };
}

export function markDropped(entry: ListEntry): ListEntryUpdate {
  return { ...toUpdate(entry), status: "dropped", dropped_at: entry.progress };
}

export function progressShare(entry: ListEntry): number | null {
  const total = totalUnits(entry.media);
  return total === null ? null : Math.min(1, entry.progress / total);
}

export function progressLabel(entry: ListEntry): string {
  const total = totalUnits(entry.media);
  const unit = unitLabel(entry.media);
  switch (entry.status) {
    case "dropped":
      return `Lâché à l'${unit} ${entry.dropped_at ?? entry.progress}`;
    case "completed":
      return total === null ? "Terminé" : `Terminé · ${total} ${unit}`;
    case "planning":
      return total === null ? "Prévu" : `Prévu · ${total} ${unit}`;
    default:
      return total === null ? `${entry.progress} ${unit}` : `${entry.progress} / ${total} ${unit}`;
  }
}
