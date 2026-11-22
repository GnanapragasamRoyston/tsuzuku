/**
 * Ton de la jaquette de secours (DESIGN.md § 1.1 « Jaquettes » et § 5.1).
 *
 * Six tons sombres, contrastes vérifiés avec ink et ink-2 (test design-tokens). La couleur
 * dominante fournie par AniList n'est JAMAIS affichée brute (elle casserait les contrastes et la
 * palette) : sa teinte choisit le ton le plus proche. Sans couleur, ou si elle est grise, le titre
 * choisit le ton, toujours le même pour une œuvre donnée (la grille ne change pas d'une visite à
 * l'autre).
 */

export type JacketTone = "wine" | "umber" | "moss" | "teal" | "indigo" | "plum";

// Teinte (degrés, 0-360) de chaque token de globals.css, calculée une fois (DESIGN.md § 1.1).
const TONE_HUES: [JacketTone, number][] = [
  ["wine", 336],
  ["umber", 28],
  ["moss", 95],
  ["teal", 185],
  ["indigo", 231],
  ["plum", 267],
];

// Classes écrites en entier : Tailwind ne génère que les classes qu'il trouve telles quelles.
export const JACKET_CLASS: Record<JacketTone, string> = {
  wine: "bg-jacket-wine",
  umber: "bg-jacket-umber",
  moss: "bg-jacket-moss",
  teal: "bg-jacket-teal",
  indigo: "bg-jacket-indigo",
  plum: "bg-jacket-plum",
};

// Sous cette saturation (écart max-min des composantes, 0 à 1), la couleur est un gris : sa
// teinte ne veut rien dire.
const MIN_CHROMA = 0.15;

function hueOf(color: string | null | undefined): number | null {
  const match = /^#([0-9a-f]{6})$/i.exec(color ?? "");
  if (!match) return null;
  const n = Number.parseInt(match[1], 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => c / 255);
  const max = Math.max(r, g, b);
  const chroma = max - Math.min(r, g, b);
  if (chroma < MIN_CHROMA) return null;
  const hue =
    max === r ? ((g - b) / chroma) % 6 : max === g ? (b - r) / chroma + 2 : (r - g) / chroma + 4;
  return (hue * 60 + 360) % 360;
}

/** FNV-1a 32 bits : un hachage simple et stable du titre. */
function hash(text: string): number {
  let h = 0x811c9dc5;
  for (const char of text) {
    h ^= char.codePointAt(0) ?? 0;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

export function jacketTone({
  title,
  cover_color,
}: {
  title: string;
  cover_color?: string | null;
}): JacketTone {
  const hue = hueOf(cover_color);
  if (hue === null) return TONE_HUES[hash(title) % TONE_HUES.length][0];
  const distance = (h: number) => Math.min(Math.abs(h - hue), 360 - Math.abs(h - hue));
  return TONE_HUES.reduce((best, cur) => (distance(cur[1]) < distance(best[1]) ? cur : best))[0];
}
