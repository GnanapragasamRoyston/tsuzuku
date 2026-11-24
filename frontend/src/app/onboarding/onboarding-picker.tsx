/**
 * Onboarding (écran STABLE, DESIGN.md § 4) : filtres → grille régulière → barre fixe en bas.
 * Au moins 10 œuvres aimées (SPEC § 8) ; elles servent aux premières recos.
 */
"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Cover } from "@/components/cover";
import { MediaTileSkeleton } from "@/components/media-tile";
import { Button } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { INPUT_CLASS } from "@/components/ui/text-field";
import { useDebounced } from "@/hooks/use-debounced";
import { ME_KEY } from "@/hooks/use-me";
import { apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/errors";
import { mediaMeta } from "@/lib/format";
import { ONBOARDING_MIN, counterLabel, toggle } from "@/lib/onboarding";
import type { MediaSummary } from "@/lib/types";
import { markUsefulAction } from "@/components/install-invite";

type Tab = "anime" | "manga" | "manhwa";
const TABS: { value: Tab; label: string; kinds: string[] }[] = [
  { value: "anime", label: "Animes", kinds: ["anime"] },
  { value: "manga", label: "Mangas", kinds: ["manga"] },
  { value: "manhwa", label: "Manhwas et manhuas", kinds: ["manhwa", "manhua"] },
];
const PAGE_SIZE = 24;

function CheckIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 12l5 5L20 7" />
    </svg>
  );
}

interface PickTileProps {
  media: MediaSummary;
  selected: boolean;
  onToggle: () => void;
}

function PickTile({ media, selected, onToggle }: PickTileProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onToggle}
      className="group flex w-full flex-col gap-2 rounded-md text-left"
    >
      <span className="relative block w-full">
        <Cover media={media} />
        {/* Sélection : contour et pastille en encre (un état, pas un signal : pas de corail). */}
        <span
          aria-hidden="true"
          className={clsx(
            "pointer-events-none absolute inset-0 rounded-md border-2 transition-colors duration-150",
            selected ? "border-ink" : "border-transparent group-hover:border-line-strong",
          )}
        />
        {selected && (
          <span className="absolute top-2 right-2 flex size-8 items-center justify-center rounded-full bg-ink text-bg">
            <CheckIcon />
          </span>
        )}
      </span>
      <span className="font-semibold leading-snug">{media.title}</span>
      <span className="text-meta font-semibold tracking-meta text-ink-2 uppercase">
        {mediaMeta(media)}
      </span>
    </button>
  );
}

export function OnboardingPicker() {
  const router = useRouter();
  const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("anime");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const query = useDebounced(search.trim());
  const kinds = TABS.find((t) => t.value === tab)?.kinds ?? ["anime"];

  const popular = useInfiniteQuery({
    queryKey: ["popular", tab],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams([
        ...kinds.map((k) => ["kind", k]),
        ["limit", String(PAGE_SIZE)],
        ["offset", String(pageParam)],
      ]);
      return apiFetch<{ items: MediaSummary[] }>(`/media/popular?${params}`);
    },
    getNextPageParam: (last, pages) =>
      last.items.length === PAGE_SIZE ? pages.length * PAGE_SIZE : undefined,
    enabled: query.length < 2,
  });

  const results = useQuery({
    queryKey: ["search", tab, query],
    queryFn: () =>
      apiFetch<{ items: MediaSummary[] }>(
        `/media/search?${new URLSearchParams([["q", query], ["limit", "48"], ...kinds.map((k) => ["kind", k])])}`,
      ),
    enabled: query.length >= 2,
  });

  const submit = useMutation({
    mutationFn: () =>
      apiFetch("/me/onboarding", { method: "POST", body: { media_ids: [...selected] } }),
    onSuccess: async () => {
      markUsefulAction(); // l'invitation à installer peut maintenant apparaître
      // Le profil de reco vient de changer : recos et liste à recharger.
      await Promise.all([ME_KEY, ["recos"], ["list"]].map((queryKey) =>
        client.invalidateQueries({ queryKey })));
      router.push("/ma-liste");
    },
    onError: (e) => setError(messageFor(e, "save")),
  });

  const searching = query.length >= 2;
  const items = searching
    ? (results.data?.items ?? [])
    : (popular.data?.pages.flatMap((p) => p.items) ?? []);
  const loading = searching ? results.isPending : popular.isPending;
  const loadError = searching ? results.error : popular.error;
  const count = selected.size;
  const ready = count >= ONBOARDING_MIN;

  return (
    <div className="mx-auto flex max-w-page flex-col gap-8 px-5 pt-12 md:px-8 lg:px-10">
      <div className="flex max-w-prose flex-col gap-4">
        <h1 className="font-display text-h1 font-bold">
          Choisis au moins {ONBOARDING_MIN} œuvres que tu as aimées
        </h1>
        <p className="text-lead text-ink-2">
          On s&apos;en sert pour tes premières recos. Tu pourras noter et compléter ta liste
          ensuite.
        </p>
      </div>

      {/* La grille est le panneau de l'onglet actif (tabpanel) : aria-controls de l'onglet pointe
          vers un élément qui existe (axe-core, aria-valid-attr-value). */}
      <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="flex flex-col gap-8">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <TabsList aria-label="Type d'œuvre">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <div className="flex flex-col gap-2 lg:w-1/3">
          <label htmlFor="recherche" className="text-small font-semibold text-ink-2">
            Chercher un titre
          </label>
          <input
            id="recherche"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="ex. Steins;Gate"
            className={INPUT_CLASS}
          />
        </div>
      </div>

      <TabsContent value={tab} className="flex flex-col gap-8">
      {loadError ? (
        <p className="text-ink-2">{messageFor(loadError)}</p>
      ) : loading ? (
        <div className="grid grid-cols-2 gap-x-6 gap-y-8 md:grid-cols-4 lg:grid-cols-6">
          {Array.from({ length: 12 }, (_, i) => (
            <MediaTileSkeleton key={i} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="text-ink-2">
          {searching ? `Aucun titre trouvé pour « ${query} ».` : "Aucun titre à proposer ici."}
        </p>
      ) : (
        <ul className="grid grid-cols-2 gap-x-6 gap-y-8 md:grid-cols-4 lg:grid-cols-6">
          {items.map((m) => (
            <li key={m.id}>
              <PickTile
                media={m}
                selected={selected.has(m.id)}
                onToggle={() => setSelected((s) => toggle(s, m.id))}
              />
            </li>
          ))}
        </ul>
      )}

      {!searching && popular.hasNextPage && (
        <Button
          className="self-center"
          onClick={() => popular.fetchNextPage()}
          loading={popular.isFetchingNextPage}
        >
          Voir plus de titres
        </Button>
      )}
      </TabsContent>
      </Tabs>

      {/* bottom-nav sur mobile : au-dessus de la barre de navigation fixe (64 px + zone de
          sécurité de l'iPhone). */}
      <div className="sticky bottom-nav z-10 -mx-5 mt-8 border-t border-line bg-surface px-5 py-4 md:bottom-0 md:-mx-8 md:px-8 lg:-mx-10 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-1 flex-col gap-2">
            <p aria-live="polite" className="tabular-nums">
              <span className="font-semibold">
                {count} sélectionné{count > 1 ? "s" : ""}
              </span>
              {" · "}
              {counterLabel(count, ONBOARDING_MIN)}
            </p>
            <ProgressBar share={Math.min(1, count / ONBOARDING_MIN)} />
          </div>
          <Button
            variant="primary"
            className="w-full md:w-auto"
            disabled={!ready}
            loading={submit.isPending}
            onClick={() => submit.mutate()}
          >
            Voir mes recos
          </Button>
        </div>
        {error && (
          <p role="alert" className="mt-2 text-small text-accent">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
