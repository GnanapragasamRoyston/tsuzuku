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
});
