/**
 * Données de « Ma liste » (TanStack Query).
 *
 * - Une liste paginée par statut ; après une action, la page est mise à jour en place
 *   (lib/list-cache.ts) et les autres onglets montés sont rechargés.
 * - Les callbacks sont au niveau du hook : ils s'exécutent pour CHAQUE action, même quand
 *   plusieurs lignes sont modifiées coup sur coup (ceux passés à mutate() ne valent que pour le
 *   dernier appel).
 * - L'ajout depuis une reco est une CRÉATION SEULE (POST) : il ne peut jamais écraser une entrée
 *   déjà avancée ou notée (revue de la phase 8).
 */
"use client";

import {
  useInfiniteQuery,
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ME_KEY } from "@/hooks/use-me";
import { apiFetch } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { applySaved, type ListPages, nextOffset } from "@/lib/list-cache";
import type { ListEntry, ListEntryUpdate, ListPage, ListStatus, RecoResponse } from "@/lib/types";

export const LIST_KEY = ["list"] as const;
const RECOS_KEY = ["recos"] as const;
const PAGE_LIMIT = 100;
const UPDATE_KEY = ["update-entry"] as const;
const ADD_KEY = ["add-entry"] as const;

export function useListPages(status: ListStatus) {
  return useInfiniteQuery({
    queryKey: [...LIST_KEY, status],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({
        status,
        limit: String(PAGE_LIMIT),
        offset: String(pageParam),
      });
      return apiFetch<ListPage>(`/me/list?${params}`);
    },
    getNextPageParam: (_last, pages) => nextOffset(pages),
  });
}

/** Compteurs de tous les statuts (onglets « En cours · 3 »), stables d'un onglet à l'autre. */
export function useListCounts() {
  return useQuery({
    queryKey: [...LIST_KEY, "counts"],
    queryFn: async () => (await apiFetch<ListPage>("/me/list?limit=1")).counts,
  });
}

interface UpdateVars {
  mediaId: number;
  update: ListEntryUpdate;
}

interface UpdateCallbacks {
  onSaved: (saved: ListEntry) => void;
  onError: (error: unknown) => void;
}

export function useUpdateEntry(tab: ListStatus, { onSaved, onError }: UpdateCallbacks) {
  const client = useQueryClient();
  return useMutation({
    mutationKey: UPDATE_KEY,
    mutationFn: ({ mediaId, update }: UpdateVars) =>
      apiFetch<ListEntry>(`/me/list/${mediaId}`, { method: "PUT", body: update }),
    onSuccess: (saved) => {
      client.setQueryData<ListPages>([...LIST_KEY, tab], (data) =>
        data ? applySaved(data, saved, tab) : data,
      );
      // Autres onglets (et compteurs) : rechargés s'ils sont montés, sinon à leur ouverture.
      client.invalidateQueries({ queryKey: LIST_KEY, predicate: (q) => q.queryKey[1] !== tab });
      onSaved(saved);
    },
    onError,
  });
}

/** Œuvres dont l'enregistrement est en cours (toutes, pas seulement la dernière cliquée). */
export function usePendingUpdates(): Set<number> {
  const ids = useMutationState({
    filters: { mutationKey: UPDATE_KEY, status: "pending" },
    select: (m) => (m.state.variables as UpdateVars | undefined)?.mediaId,
  });
  return new Set(ids.filter((id): id is number => id !== undefined));
}

/** Recos animes. `k` dans la clé : l'aside de Ma liste (6) et la page Pour toi (12) ont chacune
 *  leur cache, invalidés ensemble par le préfixe RECOS_KEY. */
export function useRecos(k = 6) {
  return useQuery({
    queryKey: [...RECOS_KEY, k],
    queryFn: () => apiFetch<RecoResponse>(`/me/recommendations?kind=anime&k=${k}`),
  });
}

/** Une seule entrée (fiche œuvre) : null si l'œuvre n'est pas dans la liste. Sous LIST_KEY : un
 *  ajout ou une modification ailleurs la recharge. */
export function useEntry(mediaId: number, enabled: boolean) {
  return useQuery({
    queryKey: [...LIST_KEY, "entry", mediaId],
    enabled,
    queryFn: async () => {
      try {
        return await apiFetch<ListEntry>(`/me/list/${mediaId}`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });
}

const PLANNED: ListEntryUpdate = {
  status: "planning",
  progress: 0,
  dropped_at: null,
  score: null,
  review: null,
  started_at: null,
  finished_at: null,
};

export function useAddPlanned(onError: (error: unknown) => void) {
  const client = useQueryClient();
  return useMutation({
    mutationKey: ADD_KEY,
    mutationFn: async (mediaId: number) => {
      try {
        await apiFetch<ListEntry>(`/me/list/${mediaId}`, { method: "POST", body: PLANNED });
      } catch (error) {
        // Déjà dans la liste (autre onglet, double clic) : rien n'a été écrasé, c'est bon.
        if (!(error instanceof ApiError && error.status === 409)) throw error;
      }
      return mediaId;
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: LIST_KEY });
      client.invalidateQueries({ queryKey: ME_KEY });
      // Les recos ne sont PAS rechargées tout de suite (la ligne « Ajouté » disparaîtrait sous le
      // pointeur) : marquées périmées, elles le seront au prochain affichage, et l'API exclut
      // alors l'œuvre ajoutée.
      client.invalidateQueries({ queryKey: RECOS_KEY, refetchType: "none" });
    },
    onError,
  });
}

/** Œuvres ajoutées depuis les recos : l'état « Ajouté » survit à un changement de page. */
export function useAddedIds(): Set<number> {
  const ids = useMutationState({
    filters: { mutationKey: ADD_KEY, status: "success" },
    select: (m) => m.state.data as number | undefined,
  });
  return new Set(ids.filter((id): id is number => id !== undefined));
}
