import { describe, expect, it } from "vitest";

import { JACKET_CLASS, isSmallCover, jacketTone } from "@/lib/jacket";

// Couleur « #rrggbb » construite à partir de ses composantes : le garde-fou du design refuse
// toute couleur hexadécimale écrite en dur dans src/, tests compris.
const rgb = (r: number, g: number, b: number) =>
  "#" + [r, g, b].map((c) => c.toString(16).padStart(2, "0")).join("");

describe("ton de la jaquette de secours (DESIGN.md § 1.1, § 5.1)", () => {
  it("la couleur AniList est ramenée au ton de la palette le plus proche en teinte", () => {
    expect(jacketTone({ title: "x", cover_color: rgb(228, 161, 93) })).toBe("umber"); // orangé
    expect(jacketTone({ title: "x", cover_color: rgb(80, 120, 228) })).toBe("indigo"); // bleu
    expect(jacketTone({ title: "x", cover_color: rgb(228, 80, 140) })).toBe("wine"); // rose
    expect(jacketTone({ title: "x", cover_color: rgb(60, 200, 200) })).toBe("teal");
  });

  it("sans couleur, ou une couleur grise, le ton vient du titre : toujours le même", () => {
    const a = jacketTone({ title: "Solo Leveling", cover_color: null });
    expect(jacketTone({ title: "Solo Leveling", cover_color: null })).toBe(a);
    expect(jacketTone({ title: "Solo Leveling", cover_color: rgb(128, 128, 128) })).toBe(a);
    const tones = new Set(
      ["One Piece", "Naruto", "Bleach", "Berserk", "Monster", "Vagabond", "Pluto", "Mushishi"].map(
        (title) => jacketTone({ title, cover_color: undefined }),
      ),
    );
    expect(tones.size).toBeGreaterThan(2); // les titres se répartissent sur la palette
  });

  it("une couleur mal formée est ignorée", () => {
    const fromTitle = jacketTone({ title: "Bleach", cover_color: null });
    expect(jacketTone({ title: "Bleach", cover_color: "rouge" })).toBe(fromTitle);
  });

  it("chaque ton a sa classe de token (aucune couleur en dur dans les composants)", () => {
    expect(Object.values(JACKET_CLASS).every((c) => /^bg-jacket-[a-z]+$/.test(c))).toBe(true);
  });
});

describe("petite image AniList (230 px) : jamais agrandie au-delà d'une jaquette en rangée", () => {
  const CDN = "https://s4.anilist.co/file/anilistcdn/media";

  it("reconnaît l'image moyenne d'AniList, anime ou manga", () => {
    // Tokyo Ghoul en production (2026-11-24) : AniList n'a que cette image, 230 × 325 px.
    expect(isSmallCover(`${CDN}/anime/cover/medium/b20605-k665mVkSug8D.jpg`)).toBe(true);
    expect(isSmallCover(`${CDN}/manga/cover/medium/b30002-abc.jpg`)).toBe(true);
  });

  it("la grande image AniList (460 px), une proposition validée ou l'absence d'image : non", () => {
    expect(isSmallCover(`${CDN}/anime/cover/large/bx1-abc.jpg`)).toBe(false);
    expect(isSmallCover("https://media.kitsu.app/anime/poster_images/1/large.jpg")).toBe(false);
    expect(isSmallCover(null)).toBe(false);
    expect(isSmallCover(undefined)).toBe(false);
  });

  it("le motif doit être dans le chemin du CDN, pas n'importe où dans l'adresse", () => {
    expect(isSmallCover("https://media.kitsu.app/x/cover/medium/1.jpg")).toBe(false);
  });
});
