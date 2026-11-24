import { describe, expect, it } from "vitest";

import {
  canPlusOne,
  criticalAlert,
  criticalMark,
  markDropped,
  parseProgress,
  plusOne,
  progressLabel,
  progressShare,
  setProgress,
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

describe("épisode choisi directement (barre glissable ou champ)", () => {
  it("garde les autres champs et passe en cours", () => {
    expect(setProgress(entry(anime(12)), 9)).toEqual({
      status: "in_progress", progress: 9, dropped_at: null, score: 8, review: "Bien",
      started_at: "2026-11-01", finished_at: null,
    });
  });

  it("le dernier épisode termine l'œuvre, comme « +1 » ; au-delà, ramené au total", () => {
    expect(setProgress(entry(anime(12)), 12)).toMatchObject({ status: "completed", progress: 12 });
    expect(setProgress(entry(anime(12)), 40)).toMatchObject({ status: "completed", progress: 12 });
  });

  it("une œuvre prévue passe en cours dès le premier épisode, reste prévue à 0", () => {
    expect(setProgress(entry(anime(12), { status: "planning", progress: 0 }), 3).status).toBe("in_progress");
    expect(setProgress(entry(anime(12), { status: "planning", progress: 0 }), 0).status).toBe("planning");
  });

  it("revenir en arrière reste possible (erreur de saisie), jamais sous 0", () => {
    expect(setProgress(entry(anime(12), { progress: 9 }), 2)).toMatchObject({ progress: 2 });
    expect(setProgress(entry(anime(12)), -4)).toMatchObject({ progress: 0 });
  });

  it("total inconnu (manga en cours) : pas de plafond, jamais terminé automatiquement", () => {
    expect(setProgress(entry(manga(null)), 312)).toMatchObject({ status: "in_progress", progress: 312 });
  });
});

describe("saisie du champ « Épisode atteint »", () => {
  it("accepte un entier entre 0 et le total, espaces et zéros en tête compris", () => {
    expect(parseProgress(" 07 ", 12)).toEqual({ ok: true, value: 7 });
    expect(parseProgress("0", 12)).toEqual({ ok: true, value: 0 });
    expect(parseProgress("12", 12)).toEqual({ ok: true, value: 12 });
  });

  it("refuse le reste avec un message qui dit quoi faire (DESIGN.md § 7)", () => {
    for (const bad of ["", "abc", "1.5", "-1", "13", "1e2"]) {
      expect(parseProgress(bad, 12)).toEqual({ ok: false, error: "Entre un nombre entre 0 et 12." });
    }
  });

  it("sans total connu : tout entier positif ou nul, dans la limite de l'API", () => {
    expect(parseProgress("1500", null)).toEqual({ ok: true, value: 1500 });
    expect(parseProgress("100001", null)).toEqual({ ok: false, error: "Entre un nombre entier, 0 ou plus." });
  });
});

describe("repère de l'épisode critique sur la barre", () => {
  it("position sur la barre, et passé ou non", () => {
    expect(criticalMark(entry(anime(12), { progress: 4, critical_episode: 9 }))).toEqual({
      episode: 9, share: 0.75, passed: false, next: false,
    });
    expect(criticalMark(entry(anime(12), { progress: 9, critical_episode: 9 }))?.passed).toBe(true);
  });

  it("« prochain » seulement quand l'épisode suivant est le critique (seul cas en corail, § 1.3)", () => {
    expect(criticalMark(entry(anime(12), { progress: 8, critical_episode: 9 }))?.next).toBe(true);
    expect(criticalMark(entry(anime(12), { progress: 7, critical_episode: 9 }))?.next).toBe(false);
    expect(criticalMark(entry(anime(12), { progress: 9, critical_episode: 9 }))?.next).toBe(false);
  });

  it("message de la ligne de liste (DESIGN.md § 7), seulement avant l'épisode critique", () => {
    expect(criticalAlert(entry(anime(12), { progress: 8, critical_episode: 9 }))).toBe(
      "Prochain épisode : le 9. C'est là que la plupart lâchent No Game No Life.",
    );
    expect(criticalAlert(entry(anime(12), { progress: 4, critical_episode: 9 }))).toBeNull();
  });

  it("aucun repère sans donnée, sans total, ou hors de la barre", () => {
    expect(criticalMark(entry(anime(12)))).toBeNull();
    expect(criticalMark(entry(anime(12), { critical_episode: null }))).toBeNull();
    expect(criticalMark(entry(anime(null), { critical_episode: 3 }))).toBeNull();
    expect(criticalMark(entry(anime(12), { critical_episode: 0 }))).toBeNull(); // avant le 1er ép.
    expect(criticalMark(entry(anime(12), { critical_episode: 30 }))).toBeNull();
  });
});
