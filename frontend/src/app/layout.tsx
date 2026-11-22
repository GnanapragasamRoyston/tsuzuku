import type { Metadata, Viewport } from "next";
import { Fraunces, Source_Sans_3 } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";

import { Providers } from "@/components/providers";
import { SiteHeader } from "@/components/site-header";
import { THEME_COLOR } from "@/lib/tokens";

import "./globals.css";

// Polices auto-hébergées par next/font (téléchargées au build) : aucune requête vers Google côté
// visiteur, donc pas de traceur tiers (DESIGN.md § 2).
const fraunces = Fraunces({
  subsets: ["latin"],
  axes: ["opsz"],
  variable: "--font-fraunces",
  display: "swap",
});
const sourceSans = Source_Sans_3({
  subsets: ["latin"],
  variable: "--font-source-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Tsuzuku — ton journal d'animes, de mangas et de manhwas",
    template: "%s · Tsuzuku",
  },
  description:
    "Suis ce que tu regardes et lis, reçois des recos, et sache à quel épisode les gens décrochent.",
};

// Couleur de la barre du navigateur mobile : token « bg » (lib/tokens.ts).
export const viewport: Viewport = { themeColor: THEME_COLOR, colorScheme: "dark" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="fr" className={`${fraunces.variable} ${sourceSans.variable}`}>
      <body className="flex min-h-dvh flex-col">
        {/* Premier élément focusable : sauter la navigation au clavier (DESIGN.md § 5.9). */}
        <a
          href="#contenu"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-20 focus:rounded-md focus:bg-raised focus:px-4 focus:py-2"
        >
          Aller au contenu
        </a>
        <Providers>
          {/* Suspense : l'en-tête lit l'URL (usePathname), connue seulement à la requête sur les
              routes dynamiques (/oeuvre/[id], /profil/[pseudo]). Sans lui, Next 16 refuse de
              pré-rendre la coquille de ces pages. Repli : une barre vide de même hauteur. */}
          <Suspense fallback={<div aria-hidden="true" className="min-h-16 border-b border-line lg:min-h-18" />}>
            <SiteHeader />
          </Suspense>
          <main id="contenu" className="flex-1">
            {children}
          </main>
        </Providers>
        {/* pb-24 : place pour la barre de navigation fixe en bas de l'écran sur mobile. */}
        <footer className="border-t border-line pb-24 md:pb-0">
          <div className="mx-auto flex max-w-page flex-wrap justify-between gap-4 px-5 py-6 text-small text-ink-2 md:px-8 lg:px-10">
            <p>Fiches et couvertures : MyAnimeList (via Jikan et le dataset Kaggle 2020), AniList.</p>
            <Link
              href="/confidentialite"
              className="inline-flex min-h-11 items-center underline-offset-4 hover:underline"
            >
              Confidentialité
            </Link>
          </div>
        </footer>
      </body>
    </html>
  );
}
