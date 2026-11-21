/**
 * Formulaires d'inscription et de connexion (écran STABLE, DESIGN.md § 4) : une colonne de
 * 480 px, libellés au-dessus, une seule action principale.
 */
"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { ME_KEY } from "@/hooks/use-me";
import { apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { safeNext } from "@/lib/redirect";

type Mode = "login" | "register";

const COPY: Record<Mode, { title: string; submit: string; switchText: string; switchLink: string; switchHref: string }> = {
  login: {
    title: "Connexion",
    submit: "Me connecter",
    switchText: "Pas encore de journal ?",
    switchLink: "Créer un compte",
    switchHref: "/inscription",
  },
  register: {
    title: "Créer ton journal",
    submit: "Créer mon compte",
    switchText: "Déjà un compte ?",
    switchLink: "Me connecter",
    switchHref: "/connexion",
  },
};

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const params = useSearchParams();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const copy = COPY[mode];

  const mutation = useMutation({
    mutationFn: (body: Record<string, string>) =>
      apiFetch(mode === "login" ? "/auth/login" : "/auth/register", { method: "POST", body }),
    onSuccess: async () => {
      // Nouvelle session : plus rien de l'ancien compte en mémoire (liste, recos), même si
      // quelqu'un d'autre était connecté dans ce navigateur. Les liens vers les pages de compte
      // ne sont pas préchargés : aucune redirection de visiteur n'est gardée en cache.
      client.clear();
      await client.invalidateQueries({ queryKey: ME_KEY });
      // Nouveau compte : onboarding d'abord. Connexion : la page demandée, sinon Ma liste.
      const next = safeNext(params.get("suivant"), "/ma-liste");
      router.push(mode === "register" ? "/onboarding" : next);
    },
    onError: (e) => setError(messageFor(e, mode)),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const data = new FormData(event.currentTarget);
    const body = Object.fromEntries(
      [...data.entries()].map(([k, v]) => [k, k === "password" ? String(v) : String(v).trim()]),
    );
    mutation.mutate(body);
  }

  return (
    <div className="mx-auto flex max-w-form flex-col gap-8 px-5 py-16 md:py-24">
      <h1 className="font-display text-h1 font-bold">{copy.title}</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-6">
        <TextField label="Email" name="email" type="email" autoComplete="email" required />
        {mode === "register" && (
          <TextField
            label="Pseudo"
            name="pseudo"
            autoComplete="username"
            required
            minLength={3}
            maxLength={20}
            pattern="[a-z0-9_]{3,20}"
            help="3 à 20 caractères : minuscules, chiffres et _. Il servira d'adresse à ton profil."
          />
        )}
        <TextField
          label="Mot de passe"
          name="password"
          type="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          required
          minLength={mode === "register" ? 10 : 1}
          maxLength={128}
          help={mode === "register" ? "10 caractères minimum. Une phrase marche très bien." : undefined}
        />
        {error && (
          <p role="alert" className="text-accent">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" loading={mutation.isPending}>
          {copy.submit}
        </Button>
      </form>
      <p className="text-ink-2">
        {copy.switchText}{" "}
        <Link href={copy.switchHref} className="text-ink underline underline-offset-4">
          {copy.switchLink}
        </Link>
      </p>
    </div>
  );
}
