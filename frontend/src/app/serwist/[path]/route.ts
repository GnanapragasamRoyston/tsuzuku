/**
 * Compile et sert le service worker (app/sw.ts) à /serwist/sw.js (@serwist/turbopack, ADR 015) :
 * Next 16 compile avec Turbopack, que l'ancien greffon webpack de Serwist ne supporte pas.
 * La route pose « Service-Worker-Allowed: / » : portée sur tout le site.
 */
import { spawnSync } from "node:child_process";

import { createSerwistRoute } from "@serwist/turbopack";

// Révision de la page hors ligne précachée : le commit déployé (Vercel le fournit), sinon git,
// sinon un identifiant aléatoire. « || » et non « ?? » : git absent renvoie une chaîne vide.
const revision =
  process.env.VERCEL_GIT_COMMIT_SHA ||
  spawnSync("git", ["rev-parse", "HEAD"], { encoding: "utf-8" }).stdout?.trim() ||
  crypto.randomUUID();

export const { dynamic, dynamicParams, revalidate, generateStaticParams, GET } = createSerwistRoute({
  additionalPrecacheEntries: [{ url: "/hors-ligne", revision }],
  swSrc: "src/app/sw.ts",
  useNativeEsbuild: true,
});
