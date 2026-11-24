/** Compte connecté : null pour un visiteur (401), sans afficher d'erreur. */
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { apiFetch } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { Me } from "@/lib/types";
import { purgePrivateData } from "@/lib/offline-cache";

export const ME_KEY = ["me"] as const;

async function fetchMe(): Promise<Me | null> {
  try {
    return await apiFetch<Me>("/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      await purgePrivateData(); // session expirée ou révoquée : rien ne reste hors ligne
      return null;
    }
    throw error;
  }
}

export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: fetchMe });
}

/**
 * Session expirée (cookie présent mais jeton refusé par l'API) : retour à la connexion, avec
 * retour prévu sur la page courante.
 */
export function useRedirectOn401(error: unknown) {
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) {
      router.replace(`/connexion?suivant=${encodeURIComponent(pathname)}`);
    }
  }, [error, router, pathname]);
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<null>("/auth/logout", { method: "POST" }),
    onSettled: async () => {
      // Plus aucune donnée du compte en mémoire après la déconnexion, ni dans le cache hors
      // ligne du service worker (téléphone partagé, ADR 015). Requêtes annulées d'abord : une
      // réponse arrivée après le vidage recréerait le cache privé.
      await client.cancelQueries();
      await purgePrivateData();
      client.clear();
      client.setQueryData(ME_KEY, null);
    },
  });
}
