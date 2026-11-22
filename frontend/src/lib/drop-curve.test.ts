import { describe, expect, it } from "vitest";

import { curveBars, curveSummary } from "@/lib/drop-curve";

// Intl fr-FR place des espaces insécables (fine avant %) : normalisées pour comparer.
const plain = (s: string) => s.replace(/[  ]/g, " ");

describe("courbe de drop (DESIGN.md § 5.5)", () => {
  it("une barre par épisode, trous comblés, parts calculées sur le total des drops", () => {
    const bars = curveBars(
      [
        { episode: 1, nb_drops: 6 },
        { episode: 3, nb_drops: 3 },
        { episode: 5, nb_drops: 1 },
      ],
      { episodes: 5, critical: 1, pointOfNoReturn: 3 },
    );
    expect(bars.map((b) => b.label)).toEqual(["1", "2", "3", "4", "5"]);
    expect(bars.map((b) => b.drops)).toEqual([6, 0, 3, 0, 1]);
    expect(bars[0].share).toBeCloseTo(0.6);
    expect(bars.map((b) => b.marker)).toEqual(["critical", null, "ponr", null, null]);
  });

  it("l'épisode 0 se lit « avant de commencer »", () => {
    const bars = curveBars([{ episode: 0, nb_drops: 2 }, { episode: 2, nb_drops: 2 }], {
      episodes: 2,
      critical: 0,
      pointOfNoReturn: null,
    });
    expect(bars[0]).toMatchObject({ label: "0", from: 0, to: 0, marker: "critical" });
    expect(bars).toHaveLength(3);
  });

  it("au-delà de 26 épisodes : tranches de 5 (1–5, 6–10…), 0 reste seul", () => {
    const points = [
      { episode: 0, nb_drops: 1 },
      { episode: 4, nb_drops: 2 },
      { episode: 5, nb_drops: 2 },
      { episode: 27, nb_drops: 5 },
    ];
    const bars = curveBars(points, { episodes: 28, critical: 27, pointOfNoReturn: 5 });
    expect(bars.map((b) => b.label)).toEqual([
      "0", "1–5", "6–10", "11–15", "16–20", "21–25", "26–28",
    ]); // prettier-ignore
    expect(bars[1].drops).toBe(4);
    expect(bars[1].marker).toBe("ponr");
    expect(bars[6].marker).toBe("critical");
  });

  it("série très longue : la tranche grandit, jamais plus de 26 barres (+ l'épisode 0)", () => {
    const bars = curveBars([{ episode: 0, nb_drops: 1 }, { episode: 480, nb_drops: 1 }], {
      episodes: 500,
      critical: 480,
      pointOfNoReturn: null,
    });
    expect(bars.length).toBeLessThanOrEqual(27);
    expect(bars[1].label).toBe("1–20");
    expect(bars.at(-1)?.to).toBe(500);
  });

  it("le critique l'emporte si les deux repères tombent dans la même tranche", () => {
    const bars = curveBars([{ episode: 30, nb_drops: 1 }], {
      episodes: 30,
      critical: 28,
      pointOfNoReturn: 29,
    });
    expect(bars.at(-1)?.marker).toBe("critical");
  });

  it("nombre d'épisodes inconnu : la courbe s'arrête au dernier épisode avec des drops", () => {
    const bars = curveBars([{ episode: 3, nb_drops: 1 }], {
      episodes: null,
      critical: 3,
      pointOfNoReturn: null,
    });
    expect(bars).toHaveLength(3);
  });

  it("aucune donnée : aucune barre", () => {
    expect(curveBars([], { episodes: 12, critical: null, pointOfNoReturn: null })).toEqual([]);
  });

  it("résumé pour le lecteur d'écran : pic et repères", () => {
    const text = curveSummary({ critical: 1, criticalShare: 0.21, pointOfNoReturn: 7 });
    expect(plain(text)).toBe(
      "Courbe de drop par épisode. Épisode critique : 1, avec 21 % des drops. " +
        "Point de non-retour : épisode 7.",
    );
  });
});
