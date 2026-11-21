/**
 * Contraste WCAG 2.x entre deux couleurs hexadécimales (#RRGGBB).
 * Sert au garde-fou des tokens (src/test/design-tokens.test.ts) : DESIGN.md § 1.2.
 */

function channel(value: number): number {
  const c = value / 255;
  // Linéarisation sRGB (seuil 0,04045 de la norme IEC 61966-2-1).
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hex: string): number {
  const match = /^#([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})$/.exec(hex);
  if (!match) throw new Error(`couleur invalide : ${hex} (attendu #RRGGBB)`);
  const [r, g, b] = match.slice(1).map((h) => channel(parseInt(h, 16)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
