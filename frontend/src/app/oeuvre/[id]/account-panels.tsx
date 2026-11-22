/**
 * Îlots « compte » de la fiche œuvre (le reste de la page est rendu côté serveur, sans cookie) :
 * - EntryPanel : ajout à la liste, ou statut + progression + note (DESIGN.md § 5.3) ;
 * - DropRiskPanel : risque de drop personnel (§ 5.4), calculé depuis la liste du compte.
 * Un visiteur voit une invitation à se connecter, jamais un faux chiffre.
 */
"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";

import { Button, ButtonLink } from "@/components/ui/button";
import { LIST_KEY, useAddPlanned, useEntry, useUpdateEntry } from "@/hooks/use-list";
import { useMe } from "@/hooks/use-me";
import { apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { formatPercent, STATUS_LABEL } from "@/lib/format";
import { progressLabel, toUpdate } from "@/lib/progress";
import type { DropRisk, ListEntry } from "@/lib/types";

const SCORES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

function loginHref(mediaId: number): string {
  return `/connexion?suivant=${encodeURIComponent(`/oeuvre/${mediaId}`)}`;
}

function Skeleton({ className }: { className: string }) {
  return <div aria-hidden="true" className={clsx("rounded-md bg-surface", className)} />;
}

// --- Liste et note -------------------------------------------------------------------------------
export function EntryPanel({ mediaId, title }: { mediaId: number; title: string }) {
  const me = useMe();
  const entry = useEntry(mediaId, Boolean(me.data));
  const [error, setError] = useState<string | null>(null);
  const add = useAddPlanned((e) => setError(messageFor(e, "save")));

  if (me.isPending || (me.data && entry.isPending)) return <Skeleton className="h-11 w-40" />;
  if (!me.data) {
    return (
      <ButtonLink href={loginHref(mediaId)} variant="primary" prefetch={false} className="self-start">
        Ajouter à ma liste
      </ButtonLink>
    );
  }
  if (entry.error) return <p className="text-ink-2">{messageFor(entry.error)}</p>;
  if (!entry.data) {
    return (
      <div className="flex flex-col items-start gap-2">
        <Button
          variant="primary"
          loading={add.isPending}
          onClick={() => {
            setError(null);
            add.mutate(mediaId);
          }}
        >
          Ajouter à ma liste
        </Button>
        {error && (
          <p role="alert" className="text-small text-accent">
            {error}
          </p>
        )}
      </div>
    );
  }
  return <InList entry={entry.data} title={title} />;
}

function InList({ entry, title }: { entry: ListEntry; title: string }) {
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const client = useQueryClient();
  const update = useUpdateEntry(entry.status, {
    onSaved: (saved) => {
      // Sans ça, les boutons montrent l'ancienne note le temps du rechargement de l'entrée.
      client.setQueryData([...LIST_KEY, "entry", saved.media.id], saved);
      setMessage(saved.score ? `Note enregistrée : ${saved.score}/10.` : "Note retirée.");
    },
    onError: (e) => setError(messageFor(e, "save")),
  });
  const saving = update.isPending;

  function rate(score: number | null) {
    setError(null);
    // Entrée ENTIÈRE (PUT) construite depuis l'état actuel : seule la note change.
    update.mutate({ mediaId: entry.media.id, update: { ...toUpdate(entry), score } });
  }

  return (
    <div className="flex flex-col gap-4">
      <p>
        Dans ta liste : <span className="font-semibold">{STATUS_LABEL[entry.status]}</span>
        {" · "}
        <span className="tabular-nums">{progressLabel(entry)}</span>{" "}
        <Link href="/ma-liste" prefetch={false} className="text-ink-2 underline">
          Gérer dans Ma liste
        </Link>
      </p>
      <fieldset className="flex flex-col gap-2" aria-describedby="note-etat">
        <legend className="mb-2 text-small font-semibold text-ink-2">Ta note</legend>
        <div className="flex flex-wrap">
          {SCORES.map((n) => (
            <label
              key={n}
              className={clsx(
                // Segments (§ 5.3) : bords partagés, arrondis aux extrémités seulement.
                "-ml-px flex min-h-11 min-w-11 cursor-pointer items-center justify-center border tabular-nums first:ml-0 first:rounded-l-md last:rounded-r-md",
                "transition-colors duration-150 has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ink",
                entry.score === n
                  ? "relative z-1 border-ink bg-raised text-ink"
                  : "border-line-strong text-ink-2 hover:bg-hover hover:text-ink",
                saving && "cursor-not-allowed",
              )}
            >
              <input
                type="radio"
                name={`note-${entry.media.id}`}
                value={n}
                checked={entry.score === n}
                disabled={saving}
                onChange={() => rate(n)}
                className="sr-only"
                aria-label={`${n} sur 10 pour ${title}`}
              />
              {n}
            </label>
          ))}
        </div>
        <p id="note-etat" className="text-small text-ink-2">
          {entry.score ? `${entry.score}/10` : "Pas encore noté"}
        </p>
      </fieldset>
      {entry.score !== null && (
        <Button variant="quiet" className="self-start" disabled={saving} onClick={() => rate(null)}>
          Retirer ma note
        </Button>
      )}
      <p aria-live="polite" className="sr-only">
        {message}
      </p>
      {error && (
        <p role="alert" className="text-small text-accent">
          {error}
        </p>
      )}
    </div>
  );
}

// --- Risque de drop ------------------------------------------------------------------------------
export function DropRiskPanel({ mediaId }: { mediaId: number }) {
  const me = useMe();
  const risk = useQuery({
    // Sous LIST_KEY : le risque dépend de toute la liste, il est rechargé après chaque ajout ou
    // modification (revue de la phase 9).
    queryKey: [...LIST_KEY, "drop-risk", mediaId],
    enabled: Boolean(me.data),
    queryFn: () => apiFetch<DropRisk>(`/me/drop-risk/${mediaId}`),
  });

  if (me.isPending || (me.data && risk.isPending)) return <Skeleton className="h-32 w-full" />;
  if (!me.data) {
    return (
      <p className="text-ink-2">
        Ton risque de lâcher cette œuvre se calcule à partir de ta liste.{" "}
        <Link href={loginHref(mediaId)} prefetch={false} className="text-ink underline">
          Connecte-toi
        </Link>{" "}
        pour le voir.
      </p>
    );
  }
  if (risk.error) return <p className="text-ink-2">{messageFor(risk.error)}</p>;
  const data = risk.data as DropRisk;
  if (data.status !== "ok" || data.probability === null || data.threshold === null) {
    return (
      <div className="flex flex-col gap-2">
        <p className="font-semibold">Pas encore assez de données</p>
        {data.message && <p className="text-ink-2">{data.message}</p>}
      </div>
    );
  }
  const atRisk = Boolean(data.at_risk);
  return (
    <div className="flex flex-col gap-2">
      <p className="font-display text-figure font-extrabold tabular-nums">
        {formatPercent(data.probability, 0)}
      </p>
      {/* Toujours chiffre + libellé + marqueur, jamais la couleur seule (§ 5.4). */}
      <p className="flex items-center gap-2 text-ui font-semibold">
        <span aria-hidden="true" className={clsx("h-6 w-1", atRisk ? "bg-accent" : "bg-good")} />
        <span className={atRisk ? "text-accent" : "text-ink"}>
          {atRisk ? "À risque" : "Risque faible"}
        </span>
      </p>
      <p className="text-small text-ink-2">Seuil du modèle : {formatPercent(data.threshold, 0)}</p>
      <p className="text-ink-2">
        Probabilité de lâcher cette œuvre, estimée par le modèle de drop à partir de ta liste (
        {data.entries_used} œuvre{data.entries_used > 1 ? "s" : ""}).
        {atRisk && data.point_of_no_return !== null
          ? ` Si tu tiens jusqu'à l'épisode ${data.point_of_no_return}, la plupart vont au bout.`
          : ""}
      </p>
    </div>
  );
}
