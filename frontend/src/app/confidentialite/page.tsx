/**
 * Confidentialité (SPEC § 7) : texte de docs/privacy.md. Page statique (aucune donnée).
 */
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Confidentialité" };

const DATA: [string, string][] = [
  ["Email", "Te connecter. Jamais affiché publiquement, jamais partagé."],
  ["Pseudo", "T'identifier dans l'appli (profil public à venir)."],
  ["Mot de passe", "Jamais stocké en clair : seulement son empreinte argon2id, qui ne permet pas de le retrouver."],
  ["Ta liste", "Statut, progression, épisode ou chapitre de drop, note, critique, dates : ta liste, tes recos, ton risque de drop."],
  ["Tes choix d'onboarding", "Tes premières recos."],
];

export default function Page() {
  return (
    <article className="mx-auto flex max-w-prose flex-col gap-8 px-5 py-16">
      <h1 className="font-display text-h1 font-bold">Confidentialité</h1>
      <section aria-labelledby="donnees" className="flex flex-col gap-4">
        <h2 id="donnees" className="font-display text-h3 font-semibold">
          Ce que Tsuzuku enregistre
        </h2>
        <dl className="flex flex-col gap-4">
          {DATA.map(([term, use]) => (
            <div key={term} className="border-b border-line pb-4">
              <dt className="font-semibold">{term}</dt>
              <dd className="text-ink-2">{use}</dd>
            </div>
          ))}
        </dl>
        <p>
          Aucun traceur tiers, aucune publicité, aucun cookie de mesure d&apos;audience. Le seul
          cookie est celui de ta session : illisible par les scripts de la page, envoyé seulement
          en HTTPS.
        </p>
      </section>
      <section aria-labelledby="droits" className="flex flex-col gap-4">
        <h2 id="droits" className="font-display text-h3 font-semibold">
          Tes droits
        </h2>
        <p>
          Depuis <Link href="/compte" className="underline underline-offset-4">ton compte</Link>, tu
          peux exporter toutes tes données dans un fichier JSON, ou supprimer ton compte : tout est
          effacé tout de suite, rien n&apos;est gardé. Tu modifies ta liste quand tu veux.
        </p>
        <p className="text-ink-2">
          Statistiques de l&apos;appli : uniquement agrégées et anonymes, jamais au niveau d&apos;un
          compte.
        </p>
      </section>
    </article>
  );
}
