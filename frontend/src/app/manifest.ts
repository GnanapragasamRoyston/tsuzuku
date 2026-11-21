import type { MetadataRoute } from "next";

import { THEME_COLOR } from "@/lib/tokens";

// Manifeste web : icônes d'application (DESIGN.md § 1.4).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Tsuzuku",
    short_name: "Tsuzuku",
    description: "Ton journal d'animes, de mangas et de manhwas.",
    lang: "fr",
    start_url: "/",
    display: "standalone",
    background_color: THEME_COLOR,
    theme_color: THEME_COLOR,
    icons: [
      { src: "/brand/tsuzuku-icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/brand/tsuzuku-icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
