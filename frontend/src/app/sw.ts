/// <reference lib="esnext" />
/// <reference lib="webworker" />
/**
 * Service worker de Tsuzuku (phase 12, SPEC § 8.1, ADR 015). Compilé par @serwist/turbopack
 * (route app/serwist/[path]) et servi à /serwist/sw.js, portée « / ».
 *
 * Chaque requête reçoit la stratégie de sa règle (lib/sw-rules.ts, testée à part) :
 * - données du compte (« Ma liste ») : RÉSEAU D'ABORD, cache privé seulement hors ligne. Avec
 *   « cache puis rafraîchi », une session expirée ou révoquée afficherait encore la liste ;
 * - catalogue public : réponse en cache tout de suite, rafraîchie en arrière-plan ;
 * - jaquettes : cache d'abord, 200 au plus, 30 jours ; fichiers statiques : cache d'abord ;
 * - pages : réseau d'abord (3 s), puis cache, puis la page « hors ligne ».
 * Les requêtes autres que GET ne passent par aucune règle : toujours le réseau.
 */
import type { PrecacheEntry, RuntimeCaching, SerwistGlobalConfig } from "serwist";
import {
  CacheFirst,
  ExpirationPlugin,
  NetworkFirst,
  NetworkOnly,
  Serwist,
  StaleWhileRevalidate,
} from "serwist";

import { PRIVATE_CACHE } from "@/lib/offline-cache";
import { type CachePolicy, cachePolicy } from "@/lib/sw-rules";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope;

const DAY = 24 * 3600;
const expiration = (maxEntries: number, days: number) =>
  new ExpirationPlugin({ maxEntries, maxAgeSeconds: days * DAY, purgeOnQuotaError: true });

const STRATEGIES: Record<CachePolicy, RuntimeCaching["handler"]> = {
  "network-only": new NetworkOnly(),
  "private-api": new NetworkFirst({
    cacheName: PRIVATE_CACHE,
    networkTimeoutSeconds: 5,
    plugins: [expiration(300, 30)],
  }),
  "public-api": new StaleWhileRevalidate({
    cacheName: "tsuzuku-public-api",
    plugins: [expiration(300, 7)],
  }),
  image: new CacheFirst({ cacheName: "tsuzuku-images", plugins: [expiration(200, 30)] }),
  static: new CacheFirst({ cacheName: "tsuzuku-static", plugins: [expiration(300, 30)] }),
  page: new NetworkFirst({
    cacheName: "tsuzuku-pages",
    networkTimeoutSeconds: 3,
    plugins: [expiration(60, 7)],
  }),
};

const runtimeCaching: RuntimeCaching[] = (Object.keys(STRATEGIES) as CachePolicy[]).map(
  (policy) => ({
    matcher: ({ url, request, sameOrigin }) =>
      cachePolicy({ url, method: request.method, sameOrigin, destination: request.destination }) ===
      policy,
    handler: STRATEGIES[policy],
  }),
);

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  // Nouvelle version active tout de suite : pas d'ancien service worker coincé chez quelqu'un.
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching,
  fallbacks: {
    entries: [
      {
        url: "/hors-ligne",
        matcher: ({ request }) => request.destination === "document",
      },
    ],
  },
});

serwist.addEventListeners();
