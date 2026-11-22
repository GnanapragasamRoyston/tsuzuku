/**
 * Pour toi (écran ÉDITORIAL, DESIGN.md § 4) : une reco « à la une » en grand, puis une rangée ;
 * sections numérotées N° 01, N° 02. Recos animes seulement : manga et manhwa demandent les recos
 * par le contenu (embeddings, phase 10) — l'API répond 501, la page le dit sans rien inventer.
 */
"use client";

import { useState } from "react";

import { RecoCard } from "@/components/reco-card";
import { SectionHeading } from "@/components/section-heading";
import { useAddedIds, useAddPlanned, useRecos } from "@/hooks/use-list";
import { useRedirectOn401 } from "@/hooks/use-me";
import { messageFor } from "@/lib/errors";
import { recoReason } from "@/lib/reco";

const PAGE = "mx-auto max-w-page px-5 md:px-8 lg:px-10";

export function ForYouPage() {
  const recos = useRecos(12);
  const added = useAddedIds();
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const add = useAddPlanned((e) => setError(messageFor(e, "save")));
  useRedirectOn401(recos.error);

  function card(item: NonNullable<typeof recos.data>["items"][number], featured = false) {
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

      <section aria-labelledby="livres" className="flex flex-col gap-4">
        <SectionHeading id="livres" number="N° 02" title="Mangas et manhwas" />
        <p className="max-w-prose text-ink-2">
          Pas encore de recos ici. Pour les mangas et les manhwas, il n&apos;y a pas d&apos;historique
          de lecteurs à comparer : les recos viendront du contenu des œuvres (genres, résumé).
          C&apos;est la prochaine étape.
        </p>
      </section>

      <p aria-live="polite" className="sr-only">
        {message}
      </p>
    </div>
  );
}
