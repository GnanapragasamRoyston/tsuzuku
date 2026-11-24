/** En ligne ou non (navigator.onLine + événements online/offline), sans rendu serveur trompeur. */
"use client";

import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

export function useOnline(): boolean {
  // Côté serveur : « en ligne » (le bandeau et les boutons désactivés n'apparaissent qu'au client).
  return useSyncExternalStore(subscribe, () => navigator.onLine, () => true);
}
