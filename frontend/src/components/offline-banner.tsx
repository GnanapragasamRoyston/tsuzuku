/** Bandeau hors ligne (DESIGN.md § 5.10) : pas une erreur, donc ni corail ni alerte. */
"use client";

import { useOnline } from "@/hooks/use-online";
import { lastSyncLabel, readLastSync } from "@/lib/offline-cache";

export function OfflineBanner() {
  const online = useOnline();
  if (online) return null;
  const sync = lastSyncLabel(readLastSync());
  return (
    <div role="status" className="border-b border-line bg-surface">
      <p className="mx-auto max-w-page px-5 py-3 text-small md:px-8 lg:px-10">
        Hors ligne. Ta liste et les fiches déjà vues restent consultables ; les modifications
        reviendront avec le réseau.{sync && <span className="text-ink-2"> {sync}.</span>}
      </p>
    </div>
  );
}
