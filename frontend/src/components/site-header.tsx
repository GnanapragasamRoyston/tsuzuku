/**
 * Navigation (DESIGN.md § 5.9). Desktop : barre haute de 72 px, logo complet, liens texte, lien
 * actif souligné de corail. Mobile : logo en haut, barre basse fixe (icône + libellé).
 */
"use client";

import clsx from "clsx";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { CompassIcon, ListIcon, SparkIcon, UserIcon } from "@/components/icons";
import { ButtonLink } from "@/components/ui/button";
import { useMe } from "@/hooks/use-me";

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
}

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function SiteHeader() {
  const pathname = usePathname();
  const { data: me, isPending } = useMe();
  const items: NavItem[] = [
    { href: "/", label: "Découvrir", icon: <CompassIcon /> },
    { href: "/ma-liste", label: "Ma liste", icon: <ListIcon /> },
    { href: "/pour-toi", label: "Pour toi", icon: <SparkIcon /> },
  ];
  // Entrée « Profil » du mobile (§ 5.9) : toujours Compte (déconnexion, export, suppression,
  // visibilité), d'où un lien mène au profil public. Pointer vers le profil public rendait Compte
  // inaccessible sur mobile (revue de la phase 9).
  const profileHref = me ? "/compte" : "/connexion";

  return (
    <>
      <header className="border-b border-line">
        <div className="mx-auto flex min-h-16 max-w-page items-center justify-between gap-4 px-5 md:px-8 lg:min-h-18 lg:px-10">
          <Link href="/" aria-label="Tsuzuku, accueil" className="flex items-center">
            <Image
              src="/brand/tsuzuku-logo-dark.svg"
              alt=""
              width={125}
              height={48}
              preload
              unoptimized
              className="h-9 w-auto lg:h-12"
            />
          </Link>
          <nav aria-label="Navigation principale" className="hidden items-center gap-2 md:flex">
            {items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                prefetch={false}
                aria-current={isActive(pathname, item.href) ? "page" : undefined}
                className={clsx(
                  "flex min-h-11 items-center border-b-2 px-3 text-ui font-semibold transition-colors duration-150",
                  isActive(pathname, item.href)
                    ? "border-accent text-ink"
                    : "border-transparent text-ink-2 hover:text-ink",
                )}
              >
                {item.label}
              </Link>
            ))}
            {isPending ? (
              // Session encore inconnue : un espace réservé plutôt que « Connexion » qui
              // clignoterait pour une personne connectée.
              <span aria-hidden="true" className="ml-4 min-h-11 w-40" />
            ) : me ? (
              <Link
                href="/compte"
                prefetch={false}
                aria-current={isActive(pathname, "/compte") ? "page" : undefined}
                className={clsx(
                  "ml-4 flex min-h-11 items-center border-b-2 px-3 text-ui font-semibold transition-colors duration-150",
                  isActive(pathname, "/compte")
                    ? "border-accent text-ink"
                    : "border-transparent text-ink-2 hover:text-ink",
                )}
              >
                {me.pseudo}
              </Link>
            ) : (
              <>
                <Link
                  href="/connexion"
                  className="ml-4 flex min-h-11 items-center px-3 text-ui font-semibold text-ink-2 hover:text-ink"
                >
                  Connexion
                </Link>
                {/* Secondaire : l'action principale corail est dans la page (DESIGN.md § 1.3). */}
                <ButtonLink href="/inscription" variant="secondary">
                  Créer mon journal
                </ButtonLink>
              </>
            )}
          </nav>
        </div>
      </header>

      <nav
        aria-label="Navigation principale"
        className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-surface pb-safe md:hidden"
      >
        <ul className="grid grid-cols-4">
          {[...items, { href: profileHref, label: me ? "Profil" : "Connexion", icon: <UserIcon /> }].map(
            (item) => {
              const active = isActive(pathname, item.href);
              return (
                <li key={item.label}>
                  <Link
                    href={item.href}
                    prefetch={false}
                    aria-current={active ? "page" : undefined}
                    className={clsx(
                      "flex min-h-16 flex-col items-center justify-center gap-1 border-t-2 text-meta font-semibold",
                      active ? "border-accent text-ink" : "border-transparent text-ink-2",
                    )}
                  >
                    {item.icon}
                    {item.label}
                  </Link>
                </li>
              );
            },
          )}
        </ul>
      </nav>
    </>
  );
}
