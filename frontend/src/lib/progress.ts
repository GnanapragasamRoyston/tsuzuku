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

/**
 * Épisode choisi directement (barre glissable ou champ, DESIGN.md § 5.2). Mêmes règles que
 * « +1 » : le dernier épisode termine l'œuvre, le premier fait passer une œuvre prévue en cours.
 * Revenir en arrière est permis (corriger une erreur).
 */
export function setProgress(entry: ListEntry, value: number): ListEntryUpdate {
  const total = totalUnits(entry.media);
  const progress = Math.max(0, total === null ? value : Math.min(total, value));
  let status: ListEntryUpdate["status"] = "in_progress";
  if (total !== null && progress >= total) status = "completed";
  else if (progress === 0 && entry.status === "planning") status = "planning";
  return { ...toUpdate(entry), status, progress, dropped_at: null };
}

// Borne de l'API (ListEntryUpdate.progress, le=100_000) quand le total de l'œuvre est inconnu.
const API_MAX_PROGRESS = 100_000;

export type ParsedProgress = { ok: true; value: number } | { ok: false; error: string };

/** Saisie du champ « Épisode atteint » : un entier, entre 0 et le total s'il est connu. */
export function parseProgress(input: string, total: number | null): ParsedProgress {
  const max = total ?? API_MAX_PROGRESS;
  const text = input.trim();
  // Chiffres seulement : ni signe, ni décimale, ni notation 1e2 (que Number accepterait).
  const value = /^\d{1,6}$/.test(text) ? Number(text) : Number.NaN;
  if (value >= 0 && value <= max) return { ok: true, value };
  return {
    ok: false,
    error: total === null ? "Entre un nombre entier, 0 ou plus." : `Entre un nombre entre 0 et ${total}.`,
  };
}

export interface CriticalMark {
  episode: number;
  /** Position sur la barre, de 0 à 1. */
  share: number;
  /** Épisode déjà vu : repère `good` (DESIGN.md § 5.2). */
  passed: boolean;
  /** C'est le prochain épisode : seul cas en corail (budget du corail, § 1.3). */
  next: boolean;
}

/** Repère de l'épisode critique sur la barre, s'il tombe sur un vrai épisode de l'œuvre. */
export function criticalMark(entry: ListEntry): CriticalMark | null {
  const total = totalUnits(entry.media);
  const episode = entry.critical_episode;
  if (total === null || episode == null || episode < 1 || episode > total) return null;
  return {
    episode,
    share: episode / total,
    passed: entry.progress >= episode,
    next: entry.progress + 1 === episode,
  };
}

/** Alerte de la ligne de liste (DESIGN.md § 7) : seulement quand l'épisode critique est le
 *  prochain, pour que le signal reste rare. */
export function criticalAlert(entry: ListEntry): string | null {
  const mark = criticalMark(entry);
  if (!mark?.next) return null;
  return `Prochain épisode : le ${mark.episode}. C'est là que la plupart lâchent ${entry.media.title}.`;
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
