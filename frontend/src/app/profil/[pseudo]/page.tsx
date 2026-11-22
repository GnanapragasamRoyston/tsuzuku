/**
 * Profil public (écran ÉDITORIAL, DESIGN.md § 4) : grands chiffres, genres favoris en liste
 * typographique, dernières notes. Opt-in (ADR 011) : un profil privé ou inconnu donne la même 404
 * côté API, donc la même page « introuvable » ici.
 */
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache, Suspense } from "react";

import { Cover } from "@/components/cover";
import { SectionHeading } from "@/components/section-heading";
import { apiFetch } from "@/lib/api";
import { PAGE } from "@/lib/layout";
import { ApiError } from "@/lib/errors";
import { formatInt, formatPercent, mediaMeta } from "@/lib/format";
import type { PublicProfile } from "@/lib/types";


type Params = Promise<{ pseudo: string }>;

const getProfile = cache(async (pseudo: string): Promise<PublicProfile | null> => {
  // Même règle que l'API (app_models.PSEUDO_PATTERN) : rien d'autre n'est envoyé dans l'URL.
  if (!/^[a-z0-9_]{3,20}$/.test(pseudo)) return null;
  try {
    return await apiFetch<PublicProfile>(`/users/${pseudo}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
});

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const profile = await getProfile((await params).pseudo).catch(() => null);
  return { title: profile ? `Profil de ${profile.pseudo}` : "Profil introuvable" };
}

export default function Page({ params }: { params: Params }) {
  return (
    <Suspense fallback={<div className={`${PAGE} py-12`} aria-hidden="true" />}>
      <Profile params={params} />
    </Suspense>
  );
}

function memberSince(month: string): string {
  const [year, m] = month.split("-").map(Number);
  return new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" }).format(
    new Date(Date.UTC(year, m - 1, 1)),
  );
}

async function Profile({ params }: { params: Params }) {
  const profile = await getProfile((await params).pseudo);
  if (!profile) notFound();
  const { counts } = profile;
  const finished = counts.completed + counts.dropped;

  return (
    <div className={`${PAGE} flex flex-col gap-16 py-12`}>
      <header className="flex items-center gap-6">
        {/* Monogramme à la place d'un avatar (pas d'upload d'image, ADR 011). */}
        <span
          aria-hidden="true"
          className="flex size-22 shrink-0 items-center justify-center rounded-full bg-surface font-display text-h1 font-bold uppercase"
        >
          {profile.pseudo[0]}
        </span>
        {/* min-w-0 + wrap-anywhere : un pseudo sans espace (« e2e_mibx… ») doit pouvoir se
            couper, sinon il élargit la page sur mobile. */}
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="font-display text-h1 font-bold wrap-anywhere">{profile.pseudo}</h1>
          <p className="text-ink-2">Membre depuis {memberSince(profile.member_since)}</p>
        </div>
      </header>

      <section aria-labelledby="chiffres" className="flex flex-col gap-8">
        <SectionHeading id="chiffres" number="N° 01" title="En chiffres" />
        <dl className="grid gap-12 md:grid-cols-3">
          <div className="flex flex-col gap-2">
            <dt className="text-ink-2">Épisodes vus</dt>
            <dd className="font-display text-figure font-extrabold tabular-nums">
              {formatInt(profile.episodes_watched)}
            </dd>
          </div>
          <div className="flex flex-col gap-2">
            <dt className="text-ink-2">Taux de drop</dt>
            <dd className="font-display text-figure font-extrabold tabular-nums">
              {profile.drop_rate === null ? "—" : formatPercent(profile.drop_rate, 0)}
            </dd>
            {profile.drop_rate === null && (
              <dd className="text-small text-ink-2">
                Pas encore assez d&apos;œuvres terminées ou lâchées ({finished}) pour un chiffre
                qui veuille dire quelque chose.
              </dd>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <dt className="text-ink-2">Terminées</dt>
            <dd className="font-display text-figure font-extrabold tabular-nums">
              {formatInt(counts.completed)}
            </dd>
            <dd className="text-small text-ink-2 tabular-nums">
              {formatInt(counts.in_progress)} en cours · {formatInt(counts.planning)} prévues ·{" "}
              {formatInt(counts.dropped)} lâchées
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="genres" className="flex flex-col gap-6">
        <SectionHeading id="genres" number="N° 02" title="Genres favoris" />
        {profile.top_genres.length > 0 ? (
          <ol className="flex flex-col gap-2">
            {profile.top_genres.map((genre, i) => (
              <li key={genre} className="flex items-baseline gap-4 font-display text-h2">
                <span className="text-ui text-ink-2 tabular-nums">{String(i + 1).padStart(2, "0")}</span>
                {genre}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-ink-2">Rien en cours ni terminé pour l&apos;instant.</p>
        )}
      </section>

      <section aria-labelledby="notes" className="flex flex-col gap-6">
        <SectionHeading id="notes" number="N° 03" title="Dernières notes" />
        {profile.recent_scores.length > 0 ? (
          <ul className="flex flex-col">
            {profile.recent_scores.map(({ media, score }) => (
              <li key={media.id} className="flex items-center gap-4 border-b border-line py-4">
                <Cover media={media} size="list" />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <h3 className="font-display text-h3 font-semibold">
                    <Link href={`/oeuvre/${media.id}`} prefetch={false} className="hover:underline">
                      {media.title}
                    </Link>
                  </h3>
                  <p className="text-meta font-semibold tracking-meta text-ink-2 uppercase">
                    {mediaMeta(media)}
                  </p>
                </div>
                <p className="font-display text-h3 font-semibold tabular-nums">{score}/10</p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-ink-2">Pas encore de note.</p>
        )}
      </section>
    </div>
  );
}
