import { describe, expect, it } from "vitest";

import { applySaved, nextOffset } from "@/lib/list-cache";
import type { ListEntry, ListPage, ListStatus, MediaSummary } from "@/lib/types";

const media = (id: number): MediaSummary => ({
  id, kind: "anime", title: `Anime ${id}`, title_alt: null, format: "TV", episodes: 12,
  chapters: null, start_year: 2010, cover_url: null, popularity: id,
});
const entry = (id: number, status: ListStatus, progress = 0): ListEntry => ({
  media: media(id), status, progress, dropped_at: null, score: null, review: null,
  started_at: null, finished_at: null, updated_at: "2026-11-21T10:00:00Z",
});
const counts = (c: Partial<Record<ListStatus, number>>) => ({
  in_progress: 0, planning: 0, completed: 0, paused: 0, dropped: 0, ...c,
});
const pages = (...p: ListPage[]) => ({ pages: p, pageParams: p.map((_, i) => i * 2) });

describe("mise à jour du cache de Ma liste après une action", () => {
  it("même statut : la ligne est remplacée sur place, l'ordre ne bouge pas", () => {
    const data = pages(
      { total: 3, counts: counts({ in_progress: 3 }), items: [entry(1, "in_progress"), entry(2, "in_progress")] },
      { total: 3, counts: counts({ in_progress: 3 }), items: [entry(3, "in_progress")] },
    );
    const out = applySaved(data, entry(2, "in_progress", 5), "in_progress");
    expect(out.pages[0].items.map((e) => [e.media.id, e.progress])).toEqual([[1, 0], [2, 5]]);
    expect(out.pages[1].items[0].media.id).toBe(3);
    expect(out.pages[0].total).toBe(3);
  });

  it("statut changé (terminé) : la ligne quitte l'onglet, compteurs et total suivent", () => {
    const data = pages(
      { total: 2, counts: counts({ in_progress: 2, completed: 4 }), items: [entry(1, "in_progress"), entry(2, "in_progress")] },
    );
    const out = applySaved(data, entry(2, "completed", 12), "in_progress");
    expect(out.pages[0].items.map((e) => e.media.id)).toEqual([1]);
    expect(out.pages[0].counts).toMatchObject({ in_progress: 1, completed: 5 });
    expect(out.pages[0].total).toBe(1);
  });

  it("ligne absente de l'onglet affiché (changement d'onglet pendant la requête) : rien ne change", () => {
    const data = pages({ total: 1, counts: counts({ completed: 1 }), items: [entry(9, "completed")] });
    expect(applySaved(data, entry(2, "completed", 12), "completed")).toBe(data);
  });

  it("ne modifie jamais les données d'origine", () => {
    const data = pages({ total: 1, counts: counts({ in_progress: 1 }), items: [entry(1, "in_progress")] });
    const frozen = JSON.stringify(data);
    applySaved(data, entry(1, "dropped", 0), "in_progress");
    expect(JSON.stringify(data)).toBe(frozen);
  });
});

describe("pagination", () => {
  it("page suivante tant que tout n'est pas chargé", () => {
    const p = (n: number, total: number): ListPage => ({
      total, counts: counts({}), items: Array.from({ length: n }, (_, i) => entry(i, "completed")),
    });
    expect(nextOffset([p(100, 250)])).toBe(100);
    expect(nextOffset([p(100, 250), p(100, 250)])).toBe(200);
    expect(nextOffset([p(100, 250), p(100, 250), p(50, 250)])).toBeUndefined();
  });
});
