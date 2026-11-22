import type { NextConfig } from "next";

// API FastAPI vue par le SERVEUR Next (jamais exposée au navigateur, qui passe par /api).
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";
const isDev = process.env.NODE_ENV === "development";

/*
 * Politique de sécurité du contenu (ADR 009). Tout vient de l'appli elle-même : polices
 * auto-hébergées par next/font, images servies par l'optimiseur de Next (/_next/image), API par le
 * relais /api. Aucun domaine tiers, donc aucun traceur possible (SPEC § 7, docs/privacy.md).
 * 'unsafe-inline' pour les scripts : Next injecte des scripts en ligne, et les nonces imposeraient
 * un rendu dynamique de chaque page. 'unsafe-eval' et ws: seulement en développement (React s'en
 * sert pour ses messages d'erreur et le rechargement à chaud).
 * upgrade-insecure-requests seulement derrière HTTPS (en production, phase 11) : en local, en
 * http, il casserait le chargement des ressources.
 */
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' blob: data:",
  "font-src 'self'",
  `connect-src 'self'${isDev ? " ws:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  ...(process.env.CSP_UPGRADE_INSECURE === "1" ? ["upgrade-insecure-requests"] : []),
].join("; ");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  images: {
    // Couvertures : CDN d'AniList (job « covers », phase 8) et de MyAnimeList (Jikan, phase 6).
    // L'optimiseur de Next les télécharge côté serveur : le visiteur ne contacte aucun tiers.
    remotePatterns: [
      new URL("https://s4.anilist.co/file/anilistcdn/**"),
      new URL("https://cdn.myanimelist.net/images/**"),
      // Jaquettes proposées par les utilisateurs et validées par Royston (ADR 012) : mêmes
      // domaines que cover_suggestion_prefixes de settings.yaml.
      new URL("https://media.kitsu.app/**"),
    ],
  },
  async rewrites() {
    // Le navigateur ne parle qu'au front : /api/me/list → API_URL/me/list (même origine, cookie
    // SameSite=Lax toujours envoyé, pas de CORS).
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
