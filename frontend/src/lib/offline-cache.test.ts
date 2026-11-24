import { describe, expect, it } from "vitest";

import { PRIVATE_CACHE, lastSyncLabel, purgePrivateData } from "@/lib/offline-cache";

describe("données privées hors ligne (ADR 015)", () => {
  it("la déconnexion efface le cache privé et la date de synchro", async () => {
    const deleted: string[] = [];
    const store = new Map([["tsuzuku-last-sync", "123"]]);
    await purgePrivateData(
      { delete: async (name: string) => (deleted.push(name), true) },
      { removeItem: (k: string) => store.delete(k) },
    );
    expect(deleted).toEqual([PRIVATE_CACHE]);
    expect(store.size).toBe(0);
  });

  it("sans Cache Storage (navigateur ancien, navigation privée) : rien ne plante", async () => {
    await expect(purgePrivateData(undefined, undefined)).resolves.toBeUndefined();
  });

  it("« Dernière synchro » en français, ou rien si inconnue", () => {
    const now = Date.UTC(2026, 10, 24, 12);
    expect(lastSyncLabel(now - 2 * 3600 * 1000, now)).toBe("Dernière synchro : il y a 2 heures");
    expect(lastSyncLabel(now - 30 * 1000, now)).toBe("Dernière synchro : à l’instant");
    expect(lastSyncLabel(null, now)).toBeNull();
  });
});
