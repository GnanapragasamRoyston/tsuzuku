/**
 * Fiche œuvre (écran STABLE, DESIGN.md § 4) : toujours dans cet ordre — en-tête (jaquette,
 * titre, méta, ajout) → risque de drop → courbe → communauté.
 *
 * Rendu côté serveur, sans cookie (catalogue public) ; seuls l'ajout, la note et le risque de
 * drop, propres au compte, sont des îlots client (account-panels.tsx).
 */
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache, Suspense } from "react";

import { Cover } from "@/components/cover";
import { DropCurve } from "@/components/drop-curve";
import { apiFetch } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { formatInt, formatPercent, mediaMeta } from "@/lib/format";
import type { MediaDetail } from "@/lib/types";

import { DropRiskPanel, EntryPanel } from "./account-panels";

const PAGE = "mx-auto max-w-page px-5 md:px-8 lg:px-10";

type Params = Promise<{ id: string }>;

// Une seule requête par rendu (métadonnées + page). null : œuvre inconnue ou identifiant invalide.
const getMedia = cache(async (id: string): Promise<MediaDetail | null> => {
  if (!/^[1-9]\d{0,9}$/.test(id)) return null;
  try {
    return await apiFetch<MediaDetail>(`/media/${id}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
});

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const media = await getMedia((await params).id).catch(() => null);
  return { title: media?.title ?? "Œuvre introuvable" };
}

export default function Page({ params }: { params: Params }) {
  return (
    <Suspense fallback={<FicheSkeleton />}>
      <Fiche params={params} />
    </Suspense>
  );
}

function FicheSkeleton() {
  return (
    <div className={`${PAGE} grid gap-8 py-12 md:grid-cols-12`} aria-hidden="true">
      <div className="aspect-2/3 rounded-md bg-surface md:col-span-4 lg:col-span-3" />
      <div className="flex flex-col gap-4 md:col-span-8">
        <div className="h-12 w-2/3 rounded-md bg-surface" />
        <div className="h-4 w-1/3 rounded-sm bg-surface" />
      </div>
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-6 border-t border-line pt-6">
      <h2 id={id} className="font-display text-h2 font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

async function Fiche({ params }: { params: Params }) {
  const media = await getMedia((await params).id);
  if (!media) notFound();
  const { critical, latest_stats: stats } = media;

  return (
    <article className={`${PAGE} flex flex-col gap-12 py-12`}>
      <header className="grid gap-8 md:grid-cols-12">
        <div className="w-2/3 md:col-span-4 md:w-full lg:col-span-3">
          <Cover media={media} eager />
        </div>
        <div className="flex flex-col gap-4 md:col-span-8 lg:col-span-9">
          <p className="text-meta font-semibold tracking-meta text-ink-2 uppercase">
            {mediaMeta(media)}
          </p>
          <h1 className="font-display text-h1 font-bold">{media.title}</h1>
          {media.title_alt && <p className="text-ink-2">{media.title_alt}</p>}
          {media.genres.length > 0 && <p className="text-ink-2">{media.genres.join(" · ")}</p>}
          <EntryPanel mediaId={media.id} title={media.title} />
          {media.synopsis && <p className="max-w-prose text-body">{media.synopsis}</p>}
        </div>
      </header>

      <Section id="risque" title="Ton risque de drop">
        <DropRiskPanel mediaId={media.id} />
      </Section>

      <Section id="courbe" title="Où les gens lâchent">
        <DropCurve media={media} />
      </Section>

      <Section id="communaute" title="Communauté">
        {critical || stats ? (
          <dl className="grid grid-cols-2 gap-6 md:grid-cols-3">
            {critical && (
              <>
                <Stat label="Taux de drop" value={formatPercent(critical.drop_rate, 0)} />
                <Stat label="Ont lâché" value={formatInt(critical.nb_drops)} />
                <Stat label="Sont allés au bout" value={formatInt(critical.nb_completed)} />
              </>
            )}
            {stats?.score !== null && stats?.score !== undefined && (
              <Stat label="Note MyAnimeList" value={`${stats.score.toLocaleString("fr-FR")}/10`} />
            )}
            {stats?.members !== null && stats?.members !== undefined && (
              <Stat label="Membres MyAnimeList" value={formatInt(stats.members)} />
            )}
          </dl>
        ) : (
          <p className="text-ink-2">Pas encore de statistiques pour cette œuvre.</p>
        )}
        <p className="text-small text-ink-2">
          {critical && "Taux de drop : lâchés / (lâchés + terminés), données MyAnimeList 2020. "}
          {stats && `Note et membres : Jikan, relevé du ${new Date(stats.snapshot_date).toLocaleDateString("fr-FR", { timeZone: "UTC" })}.`}
        </p>
      </Section>
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-small text-ink-2">{label}</dt>
      <dd className="font-display text-h2 font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
