/**
 * Compte (écran STABLE) : déconnexion, export des données, suppression (RGPD, SPEC § 7-8).
 * L'export est un lien direct vers l'API (fichier JSON téléchargé, cookie envoyé par le
 * navigateur) ; la suppression redemande le mot de passe, comme l'exige l'API.
 */
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { Button, buttonClass } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { useLogout, useMe } from "@/hooks/use-me";
import { apiFetch } from "@/lib/api";
import { ApiError, messageFor } from "@/lib/errors";

export function Account() {
  const router = useRouter();
  const client = useQueryClient();
  const me = useMe();
  const logout = useLogout();
  // Vrai dès que le compte est supprimé : la session disparaît alors volontairement, il ne faut
  // pas la traiter comme expirée (test de la phase 8 : on finissait sur /connexion?suivant=/compte).
  const deleted = useRef(false);
  // Session expirée (useMe renvoie null sur un 401) : retour à la connexion.
  useEffect(() => {
    if (me.data === null && !deleted.current) router.replace("/connexion?suivant=/compte");
  }, [me.data, router]);
  const [error, setError] = useState<string | null>(null);

  const remove = useMutation({
    mutationFn: (password: string) => apiFetch("/me", { method: "DELETE", body: { password } }),
    onSuccess: () => {
      deleted.current = true;
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
          onClick={() => logout.mutate(undefined, { onSettled: () => router.push("/") })}
        >
          Me déconnecter
        </Button>
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
