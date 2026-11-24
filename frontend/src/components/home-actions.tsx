/**
 * Boutons du haut de l'accueil, selon la session (lib/home.ts). Composant client : l'accueil est
 * rendu côté serveur SANS cookie (page publique, mise en cache), seule cette partie dépend du
 * compte.
 */
"use client";

import { ButtonLink } from "@/components/ui/button";
import { useMe } from "@/hooks/use-me";
import { heroActions } from "@/lib/home";

export function HomeActions() {
  const { data: me, isPending } = useMe();
  if (isPending) {
    // Session encore inconnue : place réservée (hauteur d'un bouton) plutôt que les boutons
    // visiteur qui clignoteraient pour une personne connectée, comme dans l'en-tête.
    return <div aria-hidden="true" className="min-h-11" />;
  }
  const { primary, secondary } = heroActions(me ?? null);
  return (
    <div className="flex flex-wrap items-center gap-6">
      {/* Pas de préchargement : une page de compte préchargée en visiteur garderait la
          redirection vers /connexion en cache (piège de l'ADR 009). */}
      <ButtonLink href={primary.href} variant="primary" prefetch={false}>
        {primary.label}
      </ButtonLink>
      <ButtonLink href={secondary.href} variant="quiet" prefetch={false}>
        {secondary.label}
      </ButtonLink>
    </div>
  );
}
