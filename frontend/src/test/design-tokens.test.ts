/**
 * Garde-fous de docs/DESIGN.md : le code ne peut pas s'écarter des tokens.
 *
 * 1. Les contrastes autorisés (§ 1.2) sont RECALCULÉS à partir de globals.css : changer un
 *    token sans revérifier casse ce test.
 * 2. Aucune couleur, police ou valeur Tailwind arbitraire en dur dans src/ (hors globals.css).
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import { contrastRatio } from "@/lib/contrast";
import { THEME_COLOR } from "@/lib/tokens";

const SRC = join(__dirname, "..");
const css = readFileSync(join(SRC, "app", "globals.css"), "utf8");

function token(name: string): string {
  const match = css.match(new RegExp(`--color-${name}:\\s*(#[0-9A-Fa-f]{6});`));
  if (!match) throw new Error(`token --color-${name} absent de globals.css`);
  return match[1];
}

// [premier plan, fond, seuil] : tableau § 1.2 de DESIGN.md.
const ALLOWED_PAIRS: [string, string, number][] = [
  ...["bg", "surface", "raised", "hover"].flatMap((bg): [string, string, number][] => [
    ["ink", bg, 4.5],
    ["ink-2", bg, 4.5],
  ]),
  ...["bg", "surface", "raised"].flatMap((bg): [string, string, number][] => [
    ["accent", bg, 4.5],
    ["good", bg, 4.5],
    ["line-strong", bg, 3],
  ]),
  // Bouton secondaire posé sur une ligne de liste survolée (revue phase 8 : 2,96:1 avant).
  ["line-strong", "hover", 3],
  ["on-accent", "accent", 4.5],
  ["on-accent", "accent-hover", 4.5],
  ["chart", "bg", 3],
  ["chart", "surface", 3],
];

describe("contrastes des tokens (WCAG AA)", () => {
  it.each(ALLOWED_PAIRS)("%s sur %s ≥ %s:1", (fg, bg, min) => {
    expect(contrastRatio(token(fg), token(bg))).toBeGreaterThanOrEqual(min);
  });

  it("la couleur de thème JavaScript reste égale au token bg", () => {
    expect(THEME_COLOR).toBe(token("bg"));
  });

  it("le texte blanc sur le corail reste interdit (sous 4,5:1)", () => {
    expect(contrastRatio(token("ink"), token("accent"))).toBeLessThan(4.5);
  });
});

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.(tsx?|css)$/.test(name) ? [path] : [];
  });
}

// Fichiers autorisés à contenir des valeurs brutes : les tokens eux-mêmes et les tests.
const EXEMPT = new Set(["app/globals.css", "lib/tokens.ts"]);
const isExempt = (rel: string) => EXEMPT.has(rel) || rel.startsWith("test/") || /\.test\.tsx?$/.test(rel);

const FORBIDDEN: [string, RegExp][] = [
  ["couleur hexadécimale en dur", /#[0-9A-Fa-f]{3,8}\b/],
  ["couleur rgb()/hsl() en dur", /\b(?:rgba?|hsla?)\(/],
  ["valeur Tailwind arbitraire", /\b(?:bg|text|border|outline|ring|fill|stroke|from|to|via|rounded(?:-[a-z]+)?|p[xytrbl]?|m[xytrbl]?|gap(?:-[xy])?|space-[xy]|w|h|min-w|min-h|max-w|max-h|size|top|left|right|bottom|inset|leading|tracking|font|shadow)-\[/],
  ["police en dur", /font-family\s*:/],
];

// Une classe hors tokens (p-5, rounded-xl) ne casse pas le build : Tailwind ne génère juste rien,
// et l'écart passerait inaperçu. On vérifie donc les pas d'espacement et les rayons utilisés.
const SPACING_KEYS = new Set(
  [...css.matchAll(/--spacing-([a-z0-9]+):/g)].map((m) => m[1]),
);
const RADIUS_KEYS = new Set([...css.matchAll(/--radius-([a-z]+):/g)].map((m) => m[1]));
const SPACING_CLASS =
  /(?<![\w-])-?(?:p[xytrbl]?|m[xytrbl]?|gap(?:-[xy])?|space-[xy]|w|h|min-w|min-h|max-h|size|top|left|right|bottom|inset(?:-[xy])?|translate-[xy]|scroll-m[xytrbl]?|scroll-p[xytrbl]?|basis)-(\d+(?:\.\d+)?|px)(?![\w./-])/g;
const RADIUS_CLASS = /(?<![\w-])rounded(?:-[trblse]{1,2})?-([a-z0-9]+)(?![\w-])/g;

describe("aucune valeur hors tokens dans src/", () => {
  const files = sourceFiles(SRC)
    .map((path) => ({ path, rel: relative(SRC, path).replaceAll("\\", "/") }))
    .filter(({ rel }) => !isExempt(rel));

  it("trouve des fichiers à vérifier", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  it.each(FORBIDDEN)("pas de %s", (_label, pattern) => {
    const offenders = files.flatMap(({ path, rel }) =>
      readFileSync(path, "utf8")
        .split("\n")
        .flatMap((line, i) => (pattern.test(line) ? [`${rel}:${i + 1}: ${line.trim()}`] : [])),
    );
    expect(offenders).toEqual([]);
  });

  it("n'utilise que les pas d'espacement et les rayons de DESIGN.md", () => {
    expect(SPACING_KEYS.has("4") && RADIUS_KEYS.has("md")).toBe(true);
    const offenders = files.flatMap(({ path, rel }) =>
      readFileSync(path, "utf8")
        .split("\n")
        .flatMap((line, i) => [
          ...[...line.matchAll(SPACING_CLASS)]
            .filter((m) => !SPACING_KEYS.has(m[1]))
            .map((m) => `${rel}:${i + 1}: ${m[0]}`),
          ...[...line.matchAll(RADIUS_CLASS)]
            .filter((m) => !RADIUS_KEYS.has(m[1]))
            .map((m) => `${rel}:${i + 1}: ${m[0]}`),
        ]),
    );
    expect(offenders).toEqual([]);
  });
});
