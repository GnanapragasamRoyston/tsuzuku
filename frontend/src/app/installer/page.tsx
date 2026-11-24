/**
 * Installer l'appli (phase 12, SPEC § 8.1, DESIGN.md § 5.10) : Android et iPhone, sans store
 * (ADR 010). Page statique.
 */
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Installer l'appli" };

function Steps({ id, title, steps }: { id: string; title: string; steps: string[] }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-4 border-t border-line pt-6">
      <h2 id={id} className="font-display text-h3 font-semibold">
        {title}
      </h2>
      <ol className="flex list-decimal flex-col gap-2 pl-5">
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
    </section>
  );
}

export default function Page() {
  return (
    <article className="mx-auto flex max-w-form flex-col gap-8 px-5 py-16">
      <div className="flex flex-col gap-4">
        <h1 className="font-display text-h1 font-bold">Installer l&apos;appli</h1>
        <p className="text-lead">
          Garde Tsuzuku sur ton écran d&apos;accueil : il s&apos;ouvre comme une appli, en plein
          écran, et ta liste reste consultable sans réseau. Pas de store, rien à payer.
        </p>
      </div>
      <Steps
        id="android"
        title="Android (Chrome)"
        steps={[
          "Ouvre Tsuzuku dans Chrome.",
          "Touche « Installer l'appli » quand Tsuzuku te le propose, ou le menu ⋮ puis « Installer l'application ».",
          "Confirme : l'icône apparaît avec tes autres applis.",
        ]}
      />
      <Steps
        id="iphone"
        title="iPhone et iPad (Safari)"
        steps={[
          "Ouvre Tsuzuku dans Safari.",
          "Touche le bouton Partager (le carré avec une flèche vers le haut).",
          "Choisis « Sur l'écran d'accueil », puis « Ajouter ».",
        ]}
      />
      <section aria-labelledby="bon-a-savoir" className="flex flex-col gap-2 border-t border-line pt-6">
        <h2 id="bon-a-savoir" className="font-display text-h3 font-semibold">
          Bon à savoir
        </h2>
        <p className="text-ink-2">
          Sur iPhone, Safari peut effacer les données d&apos;un site non installé après quelques
          jours sans visite : pour garder ta liste hors ligne, installe l&apos;appli.
        </p>
        <p className="text-ink-2">
          Hors ligne, tu peux lire ta liste et les fiches déjà vues ; les modifications reviennent
          avec le réseau.
        </p>
      </section>
    </article>
  );
}
