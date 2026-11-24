/**
 * Compte (écran STABLE) : déconnexion, profil public (opt-in, phase 9), export des données, suppression (RGPD, SPEC § 7-8).
 * L'export est un lien direct vers l'API (fichier JSON téléchargé, cookie envoyé par le
 * navigateur) ; la suppression redemande le mot de passe, comme l'exige l'API.
 */
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button, buttonClass } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { ME_KEY, useLogout, useMe } from "@/hooks/use-me";
import { apiFetch } from "@/lib/api";
import { ApiError, messageFor } from "@/lib/errors";
import type { Me } from "@/lib/types";
import { purgePrivateData } from "@/lib/offline-cache";
import { useOnline } from "@/hooks/use-online";

export function Account() {
  const router = useRouter();
  const client = useQueryClient();
  const me = useMe();
  const logout = useLogout();
  const online = useOnline();
  // Vrai dès que le compte est supprimé : la session disparaît alors volontairement, il ne faut
  // pas la traiter comme expirée (test de la phase 8 : on finissait sur /connexion?suivant=/compte).
  const deleted = useRef(false);
  // Session expirée (useMe renvoie null sur un 401) : retour à la connexion.
  useEffect(() => {
    if (me.data === null && !deleted.current) router.replace("/connexion?suivant=/compte");
  }, [me.data, router]);
  const [error, setError] = useState<string | null>(null);

  const [visibilityError, setVisibilityError] = useState<string | null>(null);
  const visibility = useMutation({
    mutationFn: (profilePublic: boolean) =>
      apiFetch<Me>("/me", { method: "PATCH", body: { profile_public: profilePublic } }),
    // Optimiste : la case suit le clic tout de suite (une case qui attend le réseau paraît
    // cassée). En cas d'échec, retour à l'état d'avant et message d'erreur.
    onMutate: (profilePublic) => {
      setVisibilityError(null);
      const previous = client.getQueryData<Me | null>(ME_KEY);
      if (previous) client.setQueryData<Me>(ME_KEY, { ...previous, profile_public: profilePublic });
      return { previous };
    },
    // Réponse de l'API = état réel enregistré.
    onSuccess: (saved) => client.setQueryData(ME_KEY, saved),
    onError: (e, _vars, context) => {
      if (context?.previous) client.setQueryData(ME_KEY, context.previous);
      setVisibilityError(messageFor(e, "save"));
    },
  });

  const remove = useMutation({
    mutationFn: (password: string) => apiFetch("/me", { method: "DELETE", body: { password } }),
    onSuccess: async () => {
      deleted.current = true;
      await client.cancelQueries(); // pas de réponse tardive qui recréerait le cache privé
      await purgePrivateData();
      client.clear();
      router.replace("/");
    },
    onError: (e) =>
      setError(
        e instanceof ApiError && e.status === 403 ? "Mot de passe incorrect." : messageFor(e, "save"),
      ),
  });

  function onDelete(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    remove.mutate(String(new FormData(event.currentTarget).get("password") ?? ""));
  }

  return (
    <div className="mx-auto flex max-w-form flex-col gap-12 px-5 py-16">
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-h1 font-bold">Ton compte</h1>
        {me.data && (
          <p className="text-ink-2">
            {me.data.pseudo} · {me.data.email}
          </p>
        )}
      </div>

      <section aria-labelledby="session" className="flex flex-col gap-4 border-t border-line pt-6">
        <h2 id="session" className="font-display text-h3 font-semibold">
          Session
        </h2>
        <p className="text-ink-2">Te déconnecte de tous tes appareils.</p>
        <Button
          className="self-start"
          loading={logout.isPending}
          disabled={!online}
          onClick={() => logout.mutate(undefined, { onSettled: () => router.push("/") })}
        >
          Me déconnecter
        </Button>
      </section>

      <section aria-labelledby="visibilite" className="flex flex-col gap-4 border-t border-line pt-6">
        <h2 id="visibilite" className="font-display text-h3 font-semibold">
          Profil public
        </h2>
        <p className="text-ink-2">
          Montre ton pseudo, tes chiffres (épisodes vus, taux de drop), tes genres favoris et tes
          dernières notes à qui a le lien. Jamais ton email ni tes critiques.
        </p>
        <label className="flex min-h-11 cursor-pointer items-center gap-3 self-start">
          <input
            type="checkbox"
            className="size-5 accent-ink"
            checked={me.data?.profile_public ?? false}
            disabled={!me.data || visibility.isPending}
            onChange={(e) => visibility.mutate(e.currentTarget.checked)}
          />
          Rendre mon profil public
        </label>
        {/* Seulement une fois l'enregistrement confirmé : avant, la page du profil répondrait
            encore « introuvable » (revue de la phase 9). */}
        {me.data?.profile_public && !visibility.isPending && (
          <Link href={`/profil/${me.data.pseudo}`} prefetch={false} className="self-start underline">
            Voir mon profil public
          </Link>
        )}
        {visibilityError && (
          <p role="alert" className="text-small text-accent">
            {visibilityError}
          </p>
        )}
      </section>

      <section aria-labelledby="export" className="flex flex-col gap-4 border-t border-line pt-6">
        <h2 id="export" className="font-display text-h3 font-semibold">
          Tes données
        </h2>
        <p className="text-ink-2">
          Ton profil, ta liste et tes choix d&apos;onboarding, dans un fichier JSON.
        </p>
        {/* Lien direct (et non fetch) : le navigateur télécharge le fichier lui-même. */}
        <a href="/api/me/export" download className={buttonClass("secondary", "self-start")}>
          Exporter mes données
        </a>
      </section>

      <section aria-labelledby="supprimer" className="flex flex-col gap-4 border-t border-line pt-6">
        <h2 id="supprimer" className="font-display text-h3 font-semibold">
          Supprimer mon compte
        </h2>
        <p className="text-ink-2">
          Efface tout de suite et pour de bon ton compte, ta liste et tes choix. Rien n&apos;est
          gardé.
        </p>
        <form onSubmit={onDelete} className="flex flex-col gap-4">
          <TextField
            label="Ton mot de passe, pour confirmer"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            error={error}
          />
          <Button
            type="submit"
            variant="destructive"
            className="self-start"
            loading={remove.isPending}
          >
            Supprimer mon compte
          </Button>
        </form>
      </section>
    </div>
  );
}
