import { describe, expect, it } from "vitest";

import { heroActions } from "@/lib/home";
import type { Me } from "@/lib/types";

const me = (overrides: Partial<Me> = {}): Me => ({
  id: 1,
  email: "roy@example.com",
  pseudo: "roy",
  created_at: "2026-11-24T00:00:00Z",
  onboarding_done: true,
  list_size: 32,
  profile_public: false,
  ...overrides,
});

describe("actions du haut de l'accueil", () => {
  it("visiteur : inscription en principal, connexion en discret", () => {
    expect(heroActions(null)).toEqual({
      primary: { href: "/inscription", label: "Commencer avec 10 titres" },
      secondary: { href: "/connexion", label: "J'ai déjà un compte" },
    });
  });

  it("connecté avec un profil de goûts : ses recos, puis sa liste (plus de « J'ai déjà un compte »)", () => {
    expect(heroActions(me())).toEqual({
      primary: { href: "/pour-toi", label: "Voir mes recos" },
      secondary: { href: "/ma-liste", label: "Ma liste" },
    });
  });

  it("connecté sans onboarding ni liste : les 10 titres d'abord (même règle que Ma liste)", () => {
    expect(heroActions(me({ onboarding_done: false, list_size: 0 })).primary).toEqual({
      href: "/onboarding",
      label: "Choisir mes 10 titres",
    });
  });

  it("onboarding sauté mais liste déjà remplie : les recos, pas l'onboarding", () => {
    expect(heroActions(me({ onboarding_done: false, list_size: 3 })).primary.href).toBe("/pour-toi");
  });
});
