/**
 * Ma liste (écran STABLE, DESIGN.md § 4) : onglets de statut → lignes identiques. À côté (dessous
 * sur mobile), « Pour toi » : les recos de base, avec ajout direct en « Prévu ».
 */
"use client";

import clsx from "clsx";
import Link from "next/link";
import { useRef, useState } from "react";

import { ListRow } from "@/components/list-row";
import { RecoCard } from "@/components/reco-card";
import { Button, ButtonLink } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useAddPlanned,
  useAddedIds,
  useListCounts,
  useListPages,
  usePendingUpdates,
  useRecos,
  useUpdateEntry,
} from "@/hooks/use-list";
import { useMe, useRedirectOn401 } from "@/hooks/use-me";
import { messageFor } from "@/lib/errors";
import { STATUS_LABEL } from "@/lib/format";
import { ONBOARDING_MIN, needsOnboarding } from "@/lib/onboarding";
import { markDropped, plusOne, progressLabel } from "@/lib/progress";
import { recoReason } from "@/lib/reco";
import type { ListEntry, ListStatus } from "@/lib/types";
import { LIST_STATUSES } from "@/lib/types";
import { InstallInvite } from "@/components/install-invite";


// Micro-textes de DESIGN.md § 7.
const EMPTY: Record<ListStatus, string> = {
  in_progress: "Rien en cours. Trouve ta prochaine série dans Pour toi.",
  planning: "Rien de prévu. Ajoute des titres depuis Pour toi.",
  completed: "Rien de terminé pour l'instant.",
  paused: "Rien en pause.",
  dropped: "Rien de lâché pour l'instant. Tu tiens bon.",
};

function savedMessage(saved: ListEntry): string {
  if (saved.status === "completed") return `${saved.media.title} passe dans Terminé.`;
  if (saved.status === "dropped") return `${saved.media.title} passe dans Lâché.`;
  // Le libellé finit souvent par « ép. » : pas de second point.
  const label = progressLabel(saved);
  return `${saved.media.title} : ${label}${label.endsWith(".") ? "" : "."}`;
}

interface StatusPanelProps {
  status: ListStatus;
  announce: (message: string) => void;
}

function StatusPanel({ status, announce }: StatusPanelProps) {
  const pages = useListPages(status);
  const pending = usePendingUpdates();
  const heading = useRef<HTMLHeadingElement>(null);
  const [error, setError] = useState<string | null>(null);
  useRedirectOn401(pages.error);

  const update = useUpdateEntry(status, {
    onSaved: (saved) => {
      announce(savedMessage(saved));
      // La ligne quitte l'onglet (terminé, lâché) : le focus irait sur <body>. On le pose sur
      // le titre du panneau, d'où la navigation au clavier reprend naturellement.
      if (saved.status !== status) heading.current?.focus();
    },
    onError: (e) => setError(messageFor(e, "save")),
  });

  function act(entry: ListEntry, kind: "plus" | "drop") {
    setError(null);
    const next = kind === "plus" ? plusOne(entry) : markDropped(entry);
    update.mutate({ mediaId: entry.media.id, update: next });
  }

  const items = pages.data?.pages.flatMap((p) => p.items) ?? [];
  let body;
  if (pages.isPending) {
    body = (
      <ul aria-hidden="true">
        {Array.from({ length: 3 }, (_, i) => (
          <li key={i} className="flex gap-4 border-b border-line py-4">
            <div className="aspect-2/3 w-22 rounded-md bg-surface" />
            <div className="flex flex-1 flex-col gap-2">
              <div className="h-6 w-1/2 rounded-sm bg-surface" />
              <div className="h-4 w-1/3 rounded-sm bg-surface" />
            </div>
          </li>
        ))}
      </ul>
    );
  } else if (pages.error) {
    body = <p className="text-ink-2">{messageFor(pages.error)}</p>;
  } else if (items.length === 0) {
    body = <p className="text-ink-2">{EMPTY[status]}</p>;
  } else {
    body = (
      <>
        {error && (
          <p role="alert" className="mb-4 text-accent">
            {error}
          </p>
        )}
        <ul className="border-t border-line">
          {items.map((entry) => (
            <ListRow
              key={entry.media.id}
              entry={entry}
              busy={pending.has(entry.media.id)}
              onPlusOne={() => act(entry, "plus")}
              onDrop={() => act(entry, "drop")}
            />
          ))}
        </ul>
        {pages.hasNextPage && (
          <Button
            className="mt-6"
            onClick={() => pages.fetchNextPage()}
            loading={pages.isFetchingNextPage}
          >
            Afficher plus
          </Button>
        )}
      </>
    );
  }
  return (
    <>
      {/* Titre de panneau (h2) : la hiérarchie reste h1 → h2 → h3 (titres de ligne). */}
      <h2 ref={heading} tabIndex={-1} className="sr-only">
        {STATUS_LABEL[status]}
      </h2>
      {body}
    </>
  );
}

function ForYou({ announce }: { announce: (message: string) => void }) {
  const recos = useRecos(3);
  const added = useAddedIds();
  const [error, setError] = useState<string | null>(null);
  const add = useAddPlanned((e) => setError(messageFor(e, "save")));
  useRedirectOn401(recos.error);

  return (
    <aside
      aria-labelledby="pour-toi"
      className="flex flex-col gap-4 lg:border-l lg:border-line lg:pl-8"
    >
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="pour-toi" className="font-display text-h2 font-semibold">
          Pour toi
        </h2>
        <Link href="/pour-toi" prefetch={false} className="text-ui font-semibold underline">
          Tout voir
        </Link>
      </div>
      {recos.isPending && <p className="text-ink-2">Un instant…</p>}
      {recos.error && <p className="text-ink-2">{messageFor(recos.error)}</p>}
      {recos.data && (
        <>
          <p className="text-small text-ink-2">{recoReason(recos.data)}</p>
          <ul className="flex flex-col gap-6">
            {/* Trois recos ici : la page Pour toi montre le reste (phase 9). */}
            {recos.data.items.map((item) => (
              <li key={item.media.id}>
                <RecoCard
                  item={item}
                  done={added.has(item.media.id)}
                  pending={add.isPending && add.variables === item.media.id}
                  onAdd={() => {
                    setError(null);
                    add.mutate(item.media.id, {
                      onSuccess: () => announce(`${item.media.title} ajouté à Prévu.`),
                    });
                  }}
                />
              </li>
            ))}
          </ul>
        </>
      )}
      {error && (
        <p role="alert" className="text-small text-accent">
          {error}
        </p>
      )}
    </aside>
  );
}

export function MyList() {
  const me = useMe();
  const counts = useListCounts();
  const [tab, setTab] = useState<ListStatus>("in_progress");
  const [message, setMessage] = useState("");
  const showOnboarding = Boolean(me.data && needsOnboarding(me.data));

  return (
    <div className="mx-auto grid max-w-page gap-12 px-5 py-12 md:px-8 lg:grid-cols-12 lg:px-10">
      {/* min-w-0 : sans lui, les onglets (plus larges que l'écran) élargissent la colonne de la
          grille et toute la page déborde sur mobile. */}
      <div className="flex min-w-0 flex-col gap-8 lg:col-span-8">
        <h1 className="font-display text-h1 font-bold">Ma liste</h1>
        {showOnboarding && (
          <div className="flex flex-col items-start gap-4 border-y border-line py-6">
            <p className="text-lead">
              Commence par choisir {ONBOARDING_MIN} œuvres que tu as aimées.
            </p>
            <ButtonLink href="/onboarding" variant="primary">
              Choisir mes {ONBOARDING_MIN} titres
            </ButtonLink>
          </div>
        )}
        <InstallInvite />
        <Tabs value={tab} onValueChange={(v) => setTab(v as ListStatus)}>
          <TabsList aria-label="Statut">
            {LIST_STATUSES.map((s) => (
              <TabsTrigger key={s} value={s}>
                {STATUS_LABEL[s]}
                <span className={clsx("ml-1", tab !== s && "text-ink-2")}>
                  · {counts.data ? counts.data[s] : "…"}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
          {LIST_STATUSES.map((s) => (
            <TabsContent key={s} value={s} className="pt-6">
              {tab === s && <StatusPanel status={s} announce={setMessage} />}
            </TabsContent>
          ))}
        </Tabs>
        {/* Annonce les changements aux lecteurs d'écran (« Death Note passe dans Terminé. »). */}
        <p aria-live="polite" className="sr-only">
          {message}
        </p>
      </div>
      <div className="min-w-0 lg:col-span-4">
        <ForYou announce={setMessage} />
      </div>
    </div>
  );
}
