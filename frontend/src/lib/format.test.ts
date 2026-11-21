import { describe, expect, it } from "vitest";

import { formatInt, formatPercent, mediaMeta } from "@/lib/format";

// Intl fr-FR utilise des espaces fines insécables : on les normalise pour comparer.
const plain = (s: string) => s.replace(/[  ]/g, " ");

describe("formats français (DESIGN.md § 2.2)", () => {
  it("milliers séparés par une espace insécable", () => {
    expect(plain(formatInt(145908))).toBe("145 908");
    expect(formatInt(145908)).not.toContain(" "); // jamais une espace ordinaire (retour à la ligne)
  });

  it("pourcentages à virgule, espace insécable avant %", () => {
    expect(plain(formatPercent(0.0283))).toBe("2,8 %");
    expect(plain(formatPercent(0.5253, 0))).toBe("53 %");
  });

  it("métadonnées d'une œuvre", () => {
    expect(mediaMeta({ kind: "anime", format: "TV", episodes: 12, chapters: null,
                       start_year: 2014 })).toBe("TV · 12 ép. · 2014");
    expect(mediaMeta({ kind: "manhwa", format: "MANGA", episodes: null, chapters: 201,
                       start_year: 2018 })).toBe("Manhwa · 201 chap. · 2018");
    expect(mediaMeta({ kind: "manga", format: null, episodes: null, chapters: null,
                       start_year: 1989 })).toBe("Manga · en cours · 1989");
    expect(mediaMeta({ kind: "anime", format: "Movie", episodes: 1, chapters: null,
                       start_year: null })).toBe("Film · 1 ép.");
  });
});
