import { describe, expect, it } from "vitest";

import { recoReason } from "@/lib/reco";

describe("phrase d'explication des recos", () => {
  it("ALS : nombre de titres aimés, accordé", () => {
    expect(recoReason({ strategy: "als", liked_used: 10 })).toBe(
      "Calculé à partir des 10 animes que tu as aimés.",
    );
    expect(recoReason({ strategy: "als", liked_used: 1 })).toBe(
      "Calculé à partir de l'anime que tu as aimé.",
    );
  });

  it("popularité : dit pourquoi, sans jargon", () => {
    expect(recoReason({ strategy: "popularity", liked_used: 0 })).toBe(
      "Les animes les plus suivis, le temps d'en savoir plus sur tes goûts.",
    );
  });

  it("contenu (mangas, manhwas) : œuvres aimées de tout type, et popularité du bon type", () => {
    expect(recoReason({ strategy: "content", liked_used: 4 }, "books")).toBe(
      "Proches de l'histoire et du ton des 4 œuvres que tu as aimées.",
    );
    expect(recoReason({ strategy: "content", liked_used: 1 }, "books")).toBe(
      "Proches de l'histoire et du ton de l'œuvre que tu as aimée.",
    );
    expect(recoReason({ strategy: "popularity", liked_used: 0 }, "books")).toBe(
      "Les plus lus, le temps d'en savoir plus sur tes goûts.",
    );
  });
});
