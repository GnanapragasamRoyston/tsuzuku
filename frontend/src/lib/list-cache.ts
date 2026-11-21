/**
 * Mise à jour en place du cache de « Ma liste » après une action (+1 ép., j'ai lâché…).
 * Fonctions pures, testées : la ligne reste où elle est (pas de nouveau tri sous le pointeur) ;
 * si son statut change, elle quitte l'onglet et les compteurs suivent.
 */
import type { ListEntry, ListPage, ListStatus } from "@/lib/types";

export interface ListPages {
  pages: ListPage[];
  pageParams: unknown[];
}

export function applySaved(data: ListPages, saved: ListEntry, tab: ListStatus): ListPages {
  const id = saved.media.id;
  const before = data.pages.flatMap((p) => p.items).find((e) => e.media.id === id);
  if (!before) return data; // la ligne n'est pas dans l'onglet affiché : rien à faire ici
  const leaves = saved.status !== tab;
  const counts = { ...data.pages[0].counts };
  if (before.status !== saved.status) {
    counts[before.status] = Math.max(0, counts[before.status] - 1);
    counts[saved.status] += 1;
  }
  return {
    ...data,
    pages: data.pages.map((page) => ({
      ...page,
      counts,
      total: leaves ? Math.max(0, page.total - 1) : page.total,
      items: leaves
        ? page.items.filter((e) => e.media.id !== id)
        : page.items.map((e) => (e.media.id === id ? saved : e)),
    })),
  };
}

/** Décalage de la page suivante, ou undefined quand toutes les entrées sont chargées. */
export function nextOffset(pages: ListPage[]): number | undefined {
  const loaded = pages.reduce((n, p) => n + p.items.length, 0);
  const total = pages[pages.length - 1]?.total ?? 0;
  return loaded < total ? loaded : undefined;
}
