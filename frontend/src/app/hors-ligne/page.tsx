/**
 * Page de secours hors ligne (phase 12, DESIGN.md § 5.10) : servie par le service worker quand une
 * page n'a jamais été ouverte et que le réseau manque. Statique et précachée (aucune donnée).
 */
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Hors ligne" };

export default function Page() {
  return (
    <article className="mx-auto flex max-w-form flex-col gap-6 px-5 py-16">
      <h1 className="font-display text-h1 font-bold">Pas de réseau</h1>
      <p className="text-lead">Cette page n&apos;a pas encore été ouverte sur cet appareil.</p>
      <ol className="flex list-decimal flex-col gap-2 pl-5 text-ink-2">
        <li>Ta liste et les fiches déjà vues restent consultables.</li>
        <li>Les modifications reviendront avec le réseau.</li>
      </ol>
      <Link href="/ma-liste" className="self-start underline">
        Ouvrir ma liste
      </Link>
    </article>
  );
}
