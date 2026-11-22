/**
 * Pour toi (écran ÉDITORIAL, DESIGN.md § 4) : une reco « à la une » en grand, puis une rangée ;
 * sections numérotées N° 01 (animes, ALS), N° 02 (mangas, manhwas et manhuas, recos par le
 * contenu de la phase 10 : le profil vient de TOUTE la liste, animes compris).
 */
"use client";

import { useState } from "react";

import { RecoCard } from "@/components/reco-card";
import { SectionHeading } from "@/components/section-heading";
import { useAddedIds, useAddPlanned, useRecos } from "@/hooks/use-list";
import { useRedirectOn401 } from "@/hooks/use-me";
import { messageFor } from "@/lib/errors";
import { PAGE } from "@/lib/layout";
import { recoReason } from "@/lib/reco";
import type { Kind, RecoItem } from "@/lib/types";


export function ForYouPage() {
  const recos = useRecos(12);
  const added = useAddedIds();
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const add = useAddPlanned((e) => setError(messageFor(e, "save")));
  useRedirectOn401(recos.error);

  function card(item: RecoItem, featured = false) {
    return (
      <RecoCard
        item={item}
        layout={featured ? "featured" : "row"}
        done={added.has(item.media.id)}
        pending={add.isPending && add.variables === item.media.id}
        onAdd={() => {
          setError(null);
          add.mutate(item.media.id, {
            onSuccess: () => setMessage(`${item.media.title} ajouté à Prévu.`),
          });
        }}
      />
    );
  }

  const [lead, ...rest] = recos.data?.items ?? [];
  return (
    <div className={`${PAGE} flex flex-col gap-16 py-12`}>
      <h1 className="font-display text-display font-bold">Pour toi</h1>

      <section aria-labelledby="animes" className="flex flex-col gap-8">
        <SectionHeading id="animes" number="N° 01" title="Animes" />
        {recos.isPending && <p className="text-ink-2">Un instant…</p>}
        {recos.error && <p className="text-ink-2">{messageFor(recos.error)}</p>}
        {recos.data && (
          <>
            <p className="text-ink-2">{recoReason(recos.data)}</p>
            {lead ? (
              <>
                {card(lead, true)}
                <ul className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
                  {rest.map((item) => (
                    <li key={item.media.id}>{card(item)}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-ink-2">
                Plus rien à te proposer pour l&apos;instant : tout est déjà dans ta liste.
              </p>
            )}
          </>
        )}
        {error && (
          <p role="alert" className="text-small text-accent">
            {error}
          </p>
        )}
      </section>

      <section aria-labelledby="livres" className="flex flex-col gap-8">
        <SectionHeading id="livres" number="N° 02" title="Mangas et manhwas" />
        <Shelf id="mangas" title="Mangas" kinds={MANGA} card={card} />
        <Shelf id="manhwas" title="Manhwas et manhuas" kinds={MANHWA} card={card} />
      </section>

      <p aria-live="polite" className="sr-only">
        {message}
      </p>
    </div>
  );
}

const MANGA: readonly Kind[] = ["manga"];
const MANHWA: readonly Kind[] = ["manhwa", "manhua"];

/** Une rangée de recos par le contenu (mangas, ou manhwas et manhuas). */
function Shelf({
  id,
  title,
  kinds,
  card,
}: {
  id: string;
  title: string;
  kinds: readonly Kind[];
  card: (item: RecoItem) => React.ReactNode;
}) {
  const recos = useRecos(6, kinds);
  return (
    <div className="flex flex-col gap-4">
      <h3 id={id} className="font-display text-h3 font-semibold">
        {title}
      </h3>
      {recos.isPending && <p className="text-ink-2">Un instant…</p>}
      {recos.error && <p className="text-ink-2">{messageFor(recos.error)}</p>}
      {recos.data && (
        <>
          <p className="text-ink-2">{recoReason(recos.data, "books")}</p>
          <ul aria-labelledby={id} className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
            {recos.data.items.map((item) => (
              <li key={item.media.id}>{card(item)}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
