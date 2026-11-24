/**
 * Accueil (écran ÉDITORIAL, DESIGN.md § 4) : titre avec grand vide à droite, rangée de
 * populaires, bandeau d'affiche avec un vrai chiffre de la base, grille asymétrique.
 * Rendu côté serveur ; chaque section charge ses données dans son propre <Suspense> : une API
 * lente ou en panne n'empêche pas le reste de la page de s'afficher.
 */
import { cache, Suspense } from "react";

import { Cover } from "@/components/cover";
import { HomeActions } from "@/components/home-actions";
import { MediaTile, MediaTileSkeleton } from "@/components/media-tile";
import { SectionHeading } from "@/components/section-heading";
import { apiFetch } from "@/lib/api";
import { PAGE } from "@/lib/layout";
import { messageFor } from "@/lib/errors";
import { formatPercent, mediaMeta } from "@/lib/format";
import type { MediaDetail, MediaSummary, TrendingResponse } from "@/lib/types";


// cache() : une seule requête par rendu pour les mêmes arguments (la rangée « Populaires » et le
// bandeau d'affiche lisent la même liste). Pas de cache entre visites pour l'instant : à décider
// avec le déploiement (phase 11).
// Types en chaîne (« manga,manhwa ») : cache() compare les arguments par valeur seulement pour
// les types simples, un tableau recréé à chaque appel ne serait jamais reconnu.
const popular = cache(async (kinds: string, limit: number): Promise<MediaSummary[]> => {
  const query = new URLSearchParams([
    ...kinds.split(",").map((k) => ["kind", k]),
    ["limit", String(limit)],
  ]);
  return (await apiFetch<{ items: MediaSummary[] }>(`/media/popular?${query}`)).items;
});

function SectionError({ error }: { error: unknown }) {
  return <p className="mt-6 text-ink-2">{messageFor(error)}</p>;
}

function RowSkeleton({ count }: { count: number }) {
  return (
    <div className="mt-6 grid grid-cols-2 gap-x-6 gap-y-8 md:grid-cols-4 lg:grid-cols-6">
      {Array.from({ length: count }, (_, i) => (
        <MediaTileSkeleton key={i} />
      ))}
    </div>
  );
}

async function PopularAnime() {
  let items: MediaSummary[];
  try {
    items = await popular("anime", 12);
  } catch (error) {
    return <SectionError error={error} />;
  }
  return (
    <ul className="mt-6 grid grid-cols-2 gap-x-6 gap-y-8 md:grid-cols-4 lg:grid-cols-6">
      {items.map((m, i) => (
        <li key={m.id}>
          <MediaTile media={m} eager={i < 6} />
        </li>
      ))}
    </ul>
  );
}

/** Bandeau d'affiche : le premier anime populaire qui a un épisode critique en base. */
async function Affiche() {
  let pick: MediaDetail | undefined;
  try {
    const candidates = (await popular("anime", 12)).slice(0, 6);
    const details = await Promise.all(
      candidates.map((m) => apiFetch<MediaDetail>(`/media/${m.id}`).catch(() => null)),
    );
    pick = details.find((d): d is MediaDetail => Boolean(d?.critical));
  } catch {
    // Bandeau décoratif : en cas d'erreur, on ne l'affiche simplement pas.
    return null;
  }
  if (!pick?.critical) return null;
  const { critical_episode, critical_drop_share, point_of_no_return } = pick.critical;
  return (
    <section aria-label="À la une" className="bg-surface">
      <div className={`${PAGE} grid gap-8 py-16 md:grid-cols-12 md:items-end md:py-24`}>
        <p className="font-display text-figure font-extrabold tabular-nums md:col-span-5">
          {formatPercent(critical_drop_share, 0)}
        </p>
        <div className="flex flex-col gap-4 md:col-span-6 md:col-start-7">
          <p className="font-display text-h2">
            des drops de <cite className="italic">{pick.title}</cite> tombent à l&apos;épisode{" "}
            {critical_episode}.
          </p>
          {point_of_no_return && (
            <p className="text-ink-2">
              Passé l&apos;épisode {point_of_no_return}, le risque de lâcher est au moins divisé par quatre.
              Ça vaut le coup de tenir.
            </p>
          )}
          <p className="text-small text-ink-2">Données MyAnimeList 2020.</p>
        </div>
      </div>
    </section>
  );
}

async function Books() {
  let items: MediaSummary[];
  try {
    items = await popular("manga,manhwa,manhua", 5);
  } catch (error) {
    return <SectionError error={error} />;
  }
  const [lead, ...rest] = items;
  if (!lead) return null;
  return (
    <div className="mt-6 grid gap-6 md:grid-cols-12">
      {/* Tête de rangée en 3 colonnes : les couvertures AniList font ~230 px de large, plus grand
          elles seraient floues. */}
      <div className="flex flex-col gap-3 md:col-span-4 lg:col-span-3">
        <Cover media={lead} largeSlot />
        <p className="font-display text-h3 font-semibold">{lead.title}</p>
        <p className="text-meta font-semibold tracking-meta text-ink-2 uppercase">
          {mediaMeta(lead)}
        </p>
      </div>
      <ul className="grid content-start gap-x-6 gap-y-8 md:col-span-8 lg:col-span-9 lg:grid-cols-2">
        {rest.map((m) => (
          <li key={m.id} className="flex items-start gap-4">
            <Cover media={m} size="list" />
            <div className="flex flex-col gap-1">
              <p className="font-semibold">{m.title}</p>
              <p className="text-meta font-semibold tracking-meta text-ink-2 uppercase">
                {mediaMeta(m)}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

async function Trending() {
  let data: TrendingResponse | null = null;
  try {
    // 4 s au plus : si Jikan est en panne, l'API peut mettre ~18 s à abandonner (retries) ; la
    // section affiche alors son message au lieu de retenir la page.
    data = await apiFetch<TrendingResponse>("/trending", { signal: AbortSignal.timeout(4000) });
  } catch {
    data = null;
  }
  if (!data || data.items.length === 0) {
    return (
      <p className="mt-6 max-w-prose text-ink-2">
        La saison en cours vient de Jikan (MyAnimeList), qui ne répond pas pour l&apos;instant. Elle
        reviendra toute seule.
      </p>
    );
  }
  return (
    <ul className="mt-6 grid grid-cols-2 gap-x-6 gap-y-8 md:grid-cols-4 lg:grid-cols-6">
      {data.items.slice(0, 12).map((t) => (
        <li key={t.mal_id} className="flex flex-col gap-2">
          <Cover media={{ title: t.title, kind: "anime", cover_url: t.cover_url }} />
          <p className="font-semibold leading-snug">{t.title}</p>
        </li>
      ))}
    </ul>
  );
}

export default function HomePage() {
  return (
    <>
      <section className={`${PAGE} grid py-16 md:grid-cols-12 md:py-24`}>
        <div className="flex flex-col gap-8 md:col-span-8">
          <p className="text-meta font-semibold tracking-meta text-ink-2 uppercase">
            Ton journal d&apos;animes, de mangas et de manhwas
          </p>
          <h1 className="font-display text-display font-extrabold tracking-tight">
            Note ce que tu regardes.
            <br />
            On te dit quand tu vas <em className="font-normal">décrocher</em>.
          </h1>
          <p className="max-w-prose text-lead text-ink-2">
            Tes recos viennent de 109 millions d&apos;entrées de listes MyAnimeList. Et pour chaque série, on sait à
            quel épisode les gens lâchent.
          </p>
          {/* Selon la session : « J'ai déjà un compte » ne s'affiche plus à une personne connectée. */}
          <HomeActions />
        </div>
      </section>

      <section aria-labelledby="populaires" className={`${PAGE} pb-16`}>
        <SectionHeading id="populaires" number="N° 01" title="Populaires" />
        <Suspense fallback={<RowSkeleton count={12} />}>
          <PopularAnime />
        </Suspense>
      </section>

      <Suspense fallback={null}>
        <Affiche />
      </Suspense>

      <section aria-labelledby="mangas" className={`${PAGE} py-16`}>
        <SectionHeading id="mangas" number="N° 02" title="Mangas et manhwas" />
        <Suspense fallback={<RowSkeleton count={5} />}>
          <Books />
        </Suspense>
      </section>

      <section aria-labelledby="saison" className={`${PAGE} pb-24`}>
        <SectionHeading id="saison" number="N° 03" title="La saison en cours" />
        <Suspense fallback={<RowSkeleton count={6} />}>
          <Trending />
        </Suspense>
      </section>
    </>
  );
}
