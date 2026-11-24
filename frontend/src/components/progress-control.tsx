/**
 * Progression d'une entrée (DESIGN.md § 5.2), partagée par Ma liste et la fiche œuvre :
 * - compteur « 7 / 24 ép. · Changer » : ouvre le champ « Épisode atteint » (un numéro précis) ;
 * - barre glissable (total connu) : un vrai <input type="range"> invisible posé sur la barre
 *   dessinée. Le curseur natif garde clavier, lecteurs d'écran et tactile ; la barre garde le
 *   style du site ;
 * - repère de l'épisode critique, en corail seulement quand c'est le prochain épisode (§ 1.3).
 *
 * Valeur « brouillon » pendant le glissement : affichée tout de suite, envoyée une seule fois au
 * relâchement (ou 600 ms après la dernière touche), pas une requête par épisode survolé.
 */
"use client";

import clsx from "clsx";
import { type FormEvent, type KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/progress-bar";
import { INPUT_CLASS } from "@/components/ui/text-field";
import {
  criticalAlert,
  criticalMark,
  parseProgress,
  progressLabel,
  progressShare,
  totalUnits,
} from "@/lib/progress";
import type { ListEntry } from "@/lib/types";

const KEYBOARD_DELAY_MS = 600;

interface ProgressControlProps {
  entry: ListEntry;
  /** En cours ou prévu : la progression se modifie. Sinon, compteur et barre figés. */
  editable: boolean;
  /** Hors ligne : rien ne peut être enregistré (DESIGN.md § 5.10). */
  disabled: boolean;
  /** Un enregistrement de cette entrée est en cours. */
  busy: boolean;
  onCommit: (value: number) => void;
}

export function ProgressControl({ entry, editable, disabled, busy, onCommit }: ProgressControlProps) {
  const { media } = entry;
  const total = totalUnits(media);
  const anime = media.kind === "anime";
  const [draft, setDraft] = useState<number | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const counter = useRef<HTMLButtonElement>(null);
  const keyTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Valeur envoyée, et si la requête a bien démarré (busy passe à true un rendu APRÈS l'envoi :
  // sans ce drapeau, le brouillon serait effacé avant même la requête, et la barre reculerait).
  const sent = useRef<{ value: number; started: boolean } | null>(null);
  const descriptionId = useId();
  const fieldId = useId();

  // Requête terminée (réussie ou refusée) : le brouillon envoyé laisse place à la valeur de l'API,
  // ou à l'ancienne en cas d'erreur, puis la valeur envoyée est oubliée. Un brouillon modifié
  // depuis (glissement repris pendant la requête) reste affiché.
  useEffect(() => {
    const pending = sent.current;
    if (!pending) return;
    if (busy) {
      pending.started = true;
      return;
    }
    if (!pending.started) return;
    sent.current = null;
    setDraft((current) => (current === pending.value ? null : current));
  }, [busy]);

  useEffect(() => () => clearTimeout(keyTimer.current), []);

  const shown = draft ?? entry.progress;
  // Vue affichée : le brouillon, avec le statut qu'il aura (une œuvre prévue passe en cours).
  const view: ListEntry = {
    ...entry,
    progress: shown,
    status: entry.status === "planning" && shown > 0 ? "in_progress" : entry.status,
  };
  const mark = criticalMark(view);
  const alert = editable ? criticalAlert(view) : null;
  const label = progressLabel(view);

  function commit(value: number) {
    clearTimeout(keyTimer.current);
    if (value === entry.progress) {
      setDraft(null);
      return;
    }
    sent.current = { value, started: false };
    onCommit(value);
  }

  function commitLater(value: number) {
    clearTimeout(keyTimer.current);
    keyTimer.current = setTimeout(() => commit(value), KEYBOARD_DELAY_MS);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = parseProgress(String(new FormData(event.currentTarget).get("progress") ?? ""), total);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setError(null);
    setEditing(false);
    setDraft(parsed.value);
    commit(parsed.value);
    // Le compteur revient à la place du champ : le focus y retourne (§ 5.2).
    requestAnimationFrame(() => counter.current?.focus());
  }

  function cancel() {
    setError(null);
    setEditing(false);
    requestAnimationFrame(() => counter.current?.focus());
  }

  const unitName = anime ? "Épisode atteint" : "Chapitre atteint";

  return (
    <div className="flex flex-col gap-1">
      {editing ? (
        <form
          onSubmit={onSubmit}
          onKeyDown={(e: KeyboardEvent) => e.key === "Escape" && cancel()}
          className="flex flex-col gap-2"
          noValidate
        >
          <label htmlFor={fieldId} className="text-small font-semibold text-ink-2">
            {unitName}
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <input
              id={fieldId}
              name="progress"
              defaultValue={entry.progress}
              inputMode="numeric"
              autoComplete="off"
              autoFocus
              onFocus={(e) => e.currentTarget.select()}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${fieldId}-erreur` : undefined}
              className={clsx(INPUT_CLASS, "w-24 tabular-nums")}
            />
            {total !== null && (
              <span className="tabular-nums text-ink-2">
                / {total} {anime ? "ép." : "chap."}
              </span>
            )}
            <Button type="submit" disabled={disabled || busy}>
              Enregistrer
            </Button>
            <Button type="button" variant="quiet" onClick={cancel}>
              Annuler
            </Button>
          </div>
          {error && (
            <p id={`${fieldId}-erreur`} role="alert" className="text-small text-accent">
              {error}
            </p>
          )}
        </form>
      ) : editable ? (
        <button
          ref={counter}
          type="button"
          onClick={() => setEditing(true)}
          disabled={disabled}
          // « 7 / 24 ép. » finit déjà par un point : pas de second.
          aria-label={`${label}${label.endsWith(".") ? "" : "."} Changer l'${anime ? "épisode" : "chapitre"} atteint pour ${media.title}`}
          className="flex min-h-11 items-center gap-2 self-start text-left tabular-nums disabled:cursor-not-allowed"
        >
          <span>{label}</span>
          <span aria-hidden="true" className="text-ink-2">
            · <span className="underline decoration-1 underline-offset-4">Changer</span>
          </span>
        </button>
      ) : (
        <p className="tabular-nums">{label}</p>
      )}

      {editable && total !== null ? (
        <div
          className={clsx(
            "relative h-11 rounded-sm",
            "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ink",
          )}
        >
          <div className="absolute inset-x-0 top-1/2 -translate-y-1/2">
            <ProgressBar share={progressShare(view)} />
          </div>
          {mark && (
            <span
              aria-hidden="true"
              className={clsx(
                "absolute top-1/2 h-3 w-1 -translate-x-1/2 -translate-y-1/2 rounded-sm",
                mark.next ? "bg-accent" : mark.passed ? "bg-good" : "bg-ink",
              )}
              style={{ left: `${mark.share * 100}%` }}
            />
          )}
          <span
            aria-hidden="true"
            className={clsx(
              "pointer-events-none absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full",
              disabled ? "bg-disabled" : "bg-ink",
            )}
            style={{ left: `${(progressShare(view) ?? 0) * 100}%` }}
          />
          <input
            type="range"
            min={0}
            max={total}
            step={1}
            value={shown}
            disabled={disabled}
            aria-label={`${unitName}, ${media.title}`}
            // Singulier pour 0 et 1, comme en français (« 1 épisode sur 12 »).
            aria-valuetext={`${shown} ${anime ? "épisode" : "chapitre"}${shown > 1 ? "s" : ""} sur ${total}`}
            aria-describedby={mark ? descriptionId : undefined}
            onChange={(e) => setDraft(Number(e.currentTarget.value))}
            onPointerUp={(e) => commit(Number(e.currentTarget.value))}
            onKeyUp={(e) => commitLater(Number(e.currentTarget.value))}
            // Glissement interrompu (geste de défilement) ou focus parti avant le délai clavier :
            // le brouillon affiché est enregistré, il ne reste jamais « faux ».
            onPointerCancel={(e) => commit(Number(e.currentTarget.value))}
            onBlur={() => draft !== null && draft !== sent.current?.value && commit(draft)}
            className="absolute inset-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
          />
          {mark && (
            <span id={descriptionId} className="sr-only">
              Épisode critique : {mark.episode}.
            </span>
          )}
        </div>
      ) : (
        <ProgressBar share={progressShare(view)} muted={entry.status === "dropped"} />
      )}

      {alert && <p className="text-small text-accent">{alert}</p>}
    </div>
  );
}
