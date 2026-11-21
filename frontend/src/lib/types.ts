/**
 * Types des réponses de l'API FastAPI (miroir des schémas Pydantic de backend/app/schemas).
 * Un champ renommé côté API doit l'être ici aussi : TypeScript signale alors chaque usage.
 */

export type Kind = "anime" | "manga" | "manhwa" | "manhua";
export type ListStatus = "planning" | "in_progress" | "completed" | "paused" | "dropped";

export const LIST_STATUSES: readonly ListStatus[] = [
  "in_progress",
  "planning",
  "completed",
  "paused",
  "dropped",
];

export interface MediaSummary {
  id: number;
  kind: Kind;
  title: string;
  title_alt: string | null;
  format: string | null;
  episodes: number | null;
  chapters: number | null;
  start_year: number | null;
  cover_url: string | null;
  popularity: number | null;
}

export interface CriticalEpisode {
  critical_episode: number;
  critical_drop_share: number;
  initial_drop_risk: number | null;
  point_of_no_return: number | null;
  drop_rate: number;
  nb_drops: number;
  nb_completed: number;
}

export interface MediaDetail extends MediaSummary {
  synopsis: string | null;
  genres: string[];
  critical: CriticalEpisode | null;
  drop_curve: { episode: number; nb_drops: number; cumulative_share: number }[];
}

export interface ListEntry {
  media: MediaSummary;
  status: ListStatus;
  progress: number;
  dropped_at: number | null;
  score: number | null;
  review: string | null;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

/** Corps de PUT /me/list/{media_id} : l'entrée ENTIÈRE (un champ absent est remis à vide). */
export type ListEntryUpdate = Omit<ListEntry, "media" | "updated_at">;

export interface ListPage {
  total: number;
  counts: Record<ListStatus, number>;
  items: ListEntry[];
}

export interface Me {
  id: number;
  email: string;
  pseudo: string;
  created_at: string;
  onboarding_done: boolean;
  list_size: number;
}

export interface RecoItem {
  media: MediaSummary;
  score: number;
  because: string | null;
}

export interface RecoResponse {
  strategy: "als" | "popularity";
  reason: string;
  liked_used: number;
  liked_ignored: number[];
  items: RecoItem[];
}

export interface TrendingItem {
  mal_id: number;
  title: string;
  cover_url: string | null;
  score: number | null;
  members: number | null;
  episodes: number | null;
  media_id: number | null;
}

export interface TrendingResponse {
  source: string;
  origin: "database" | "live";
  fetched_at: string;
  stale: boolean;
  items: TrendingItem[];
}
