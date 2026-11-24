// Icône « maskable » (Android, phase 12) depuis le logo : fond corail plein (Android découpe la
// forme lui-même) et symbole réduit à 70 % au centre, dans la zone de sécurité (cercle de 80 %).
// Lancement : node scripts/maskable-icon.mjs (depuis frontend/).
import { readFileSync } from "node:fs";

import sharp from "sharp";

const svg = readFileSync("public/brand/tsuzuku-icon.svg", "utf-8");
const match = svg.match(/<rect[^>]*fill="(#[0-9A-Fa-f]{6})"[^>]*\/>([\s\S]*)<\/svg>/);
if (!match) throw new Error("tsuzuku-icon.svg : structure inattendue (rect + symbole)");
const [, background, glyph] = match;
const maskable = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" fill="${background}"/>
<g transform="translate(76.8 76.8) scale(0.7)">${glyph}</g></svg>`;
await sharp(Buffer.from(maskable)).resize(512, 512).png().toFile("public/brand/tsuzuku-maskable-512.png");
console.log("public/brand/tsuzuku-maskable-512.png");
