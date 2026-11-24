/**
 * TanStack Query pour les données du compte (lues dans le navigateur, avec le cookie de session).
 * Un client par rendu serveur, un seul dans le navigateur (guide Next 16, client-side fetching).
 */
"use client";

import { SerwistProvider } from "@serwist/turbopack/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/errors";

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Hors ligne, la requête part quand même : le service worker répond depuis son cache
        // (sinon TanStack Query la met en pause et « Ma liste » ne s'affiche jamais).
        networkMode: "offlineFirst",
        staleTime: 30_000,
        // On ne réessaie pas une erreur « normale » (401, 404, 422…) : seulement le réseau et 5xx.
        retry: (failures, error) =>
          failures < 2 && !(error instanceof ApiError && error.status < 500),
        refetchOnWindowFocus: false,
      },
    },
  });
}

let browserClient: QueryClient | undefined;

function getClient(): QueryClient {
  if (typeof window === "undefined") return makeClient();
  browserClient ??= makeClient();
  return browserClient;
}

export function Providers({ children }: { children: ReactNode }) {
  return (
    // Service worker (PWA, ADR 015) : désactivé en développement (Turbopack recompile sans cesse,
    // un cache y cacherait les modifications) ; actif dans le build de production et l'E2E.
    // cacheOnNavigation : les pages ouvertes par navigation interne sont gardées pour le hors
    // ligne (elles ne passent pas par le service worker comme document).
    <SerwistProvider
      swUrl="/serwist/sw.js"
      disable={process.env.NODE_ENV === "development"}
      cacheOnNavigation
    >
      <QueryClientProvider client={getClient()}>{children}</QueryClientProvider>
    </SerwistProvider>
  );
}
