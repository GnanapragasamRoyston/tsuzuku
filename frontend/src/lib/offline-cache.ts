/**
 * Données privées gardées hors ligne (ADR 015) : « Ma liste » et le compte, dans un cache à part
 * (PRIVATE_CACHE, rempli par le service worker), plus la date de dernière synchro.
 * Effacées à la déconnexion, à la suppression du compte et à toute session refusée (401) : sur un
 * téléphone partagé, la personne suivante ne voit jamais la liste de la précédente.
 */

export const PRIVATE_CACHE = "tsuzuku-private";
export const LAST_SYNC_KEY = "tsuzuku-last-sync";

interface CacheStorageLike {
  delete(name: string): Promise<boolean>;
}
interface StorageLike {
  removeItem(key: string): void;
}

export async function purgePrivateData(
  caches: CacheStorageLike | undefined = typeof window !== "undefined" ? window.caches : undefined,
  storage: StorageLike | undefined = typeof window !== "undefined" ? window.localStorage : undefined,
): Promise<void> {
  try {
    await caches?.delete(PRIVATE_CACHE);
  } catch {
    // Cache Storage indisponible (navigation privée, ancien navigateur) : rien à effacer.
  }
  storage?.removeItem(LAST_SYNC_KEY);
}

const RELATIVE = new Intl.RelativeTimeFormat("fr-FR", { numeric: "auto" });
const STEPS: [number, Intl.RelativeTimeFormatUnit][] = [
  [24 * 3600, "day"],
  [3600, "hour"],
  [60, "minute"],
];

export function lastSyncLabel(syncedAt: number | null, now: number = Date.now()): string | null {
  if (syncedAt === null) return null;
  const seconds = Math.max(0, (now - syncedAt) / 1000);
  for (const [size, unit] of STEPS) {
    if (seconds >= size) {
      return `Dernière synchro : ${RELATIVE.format(-Math.round(seconds / size), unit)}`;
    }
  }
  return "Dernière synchro : à l’instant";
}

export function readLastSync(): number | null {
  if (typeof window === "undefined") return null;
  const value = Number(window.localStorage.getItem(LAST_SYNC_KEY));
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function markSynced(): void {
  if (typeof window !== "undefined" && navigator.onLine) {
    try {
      window.localStorage.setItem(LAST_SYNC_KEY, String(Date.now()));
    } catch {
      // Stockage plein ou bloqué : pas de date de synchro, la liste, elle, est chargée.
    }
  }
}
