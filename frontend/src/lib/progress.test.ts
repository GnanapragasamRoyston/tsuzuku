import { describe, expect, it } from "vitest";

import {
  canPlusOne,
  markDropped,
  plusOne,
  progressLabel,
  progressShare,
  toUpdate,
  totalUnits,
} from "@/lib/progress";
import type { ListEntry, MediaSummary } from "@/lib/types";

const anime = (episodes: number | null): MediaSummary => ({
  id: 7207, kind: "anime", title: "No Game No Life", title_alt: null, format: "TV",
  episodes, chapters: null, start_year: 2014, cover_url: null, popularity: 12,
});
const manga = (chapters: number | null): MediaSummary => ({
  id: 64857, kind: "manga", title: "Chainsaw Man", title_alt: null, format: "MANGA",
  episodes: null, chapters, start_year: 2018, cover_url: null, popularity: 1,
});

function entry(media: MediaSummary, over: Partial<ListEntry> = {}): ListEntry {
  return {
    media, status: "in_progress", progress: 4, dropped_at: null, score: 8, review: "Bien",
    started_at: "2026-11-01", finished_at: null, updated_at: "2026-11-20T10:00:00Z", ...over,
  };
}

describe("total d'unités", () => {
  it("épisodes pour un anime, chapitres sinon, inconnu si absent ou nul", () => {
    expect(totalUnits(anime(12))).toBe(12);
    expect(totalUnits(manga(232))).toBe(232);
    expect(totalUnits(anime(null))).toBeNull();
    expect(totalUnits(anime(0))).toBeNull();
  });
});

describe("+1 épisode", () => {
  it("avance d'une unité et garde les autres champs (le PUT remplace toute l'entrée)", () => {
    expect(plusOne(entry(anime(12)))).toEqual({
      status: "in_progress", progress: 5, dropped_at: null, score: 8, review: "Bien",
      started_at: "2026-11-01", finished_at: null,
    });
  });

  it("passe un titre prévu en cours", () => {
    expect(plusOne(entry(anime(12), { status: "planning", progress: 0 })).status).toBe("in_progress");
  });

  it("au dernier épisode, marque comme terminé", () => {
    const update = plusOne(entry(anime(12), { progress: 11 }));
    expect(update).toMatchObject({ status: "completed", progress: 12 });
  });

  it("sans total connu, avance sans jamais terminer", () => {
    expect(plusOne(entry(manga(null), { progress: 300 }))).toMatchObject({
      status: "in_progress", progress: 301,
    });
  });

  it("n'est plus proposé une fois le total atteint", () => {
    expect(canPlusOne(entry(anime(12), { progress: 12 }))).toBe(false);
    expect(canPlusOne(entry(anime(12), { progress: 11 }))).toBe(true);
    expect(canPlusOne(entry(manga(null), { progress: 999 }))).toBe(true);
  });
});

describe("j'ai lâché", () => {
  it("passe en lâché à l'épisode atteint", () => {
    expect(markDropped(entry(anime(12), { progress: 3 }))).toMatchObject({
      status: "dropped", progress: 3, dropped_at: 3, score: 8,
    });
  });
});

describe("affichage de la progression", () => {
  it("part vue, ou inconnue sans total", () => {
    expect(progressShare(entry(anime(12), { progress: 3 }))).toBeCloseTo(0.25);
    expect(progressShare(entry(manga(null)))).toBeNull();
  });

  it("libellés selon le statut et l'unité", () => {
    expect(progressLabel(entry(anime(24), { progress: 7 }))).toBe("7 / 24 ép.");
    expect(progressLabel(entry(manga(null), { progress: 41 }))).toBe("41 chap.");
    expect(progressLabel(entry(anime(25), { status: "dropped", progress: 3, dropped_at: 3 }))).toBe(
      "Lâché à l'ép. 3",
    );
    expect(progressLabel(entry(anime(37), { status: "completed", progress: 37 }))).toBe(
      "Terminé · 37 ép.",
    );
    expect(progressLabel(entry(anime(12), { status: "planning", progress: 0 }))).toBe("Prévu · 12 ép.");
  });

  it("toUpdate recopie exactement les champs modifiables", () => {
    expect(Object.keys(toUpdate(entry(anime(12)))).sort()).toEqual(
      ["dropped_at", "finished_at", "progress", "review", "score", "started_at", "status"],
    );
  });
});
