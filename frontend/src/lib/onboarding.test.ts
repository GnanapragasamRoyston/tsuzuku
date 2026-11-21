import { describe, expect, it } from "vitest";

import { counterLabel, toggle } from "@/lib/onboarding";

describe("sélection d'onboarding", () => {
  it("ajoute puis retire, sans modifier l'ensemble d'origine", () => {
    const empty = new Set<number>();
    const one = toggle(empty, 4954);
    expect([...one]).toEqual([4954]);
    expect(empty.size).toBe(0);
    expect(toggle(one, 4954).size).toBe(0);
  });

  it("compteur (micro-texte de DESIGN.md § 7)", () => {
    expect(counterLabel(6, 10)).toBe("Encore 4 titres et tes recos sont prêtes.");
    expect(counterLabel(9, 10)).toBe("Encore 1 titre et tes recos sont prêtes.");
    expect(counterLabel(10, 10)).toBe("C'est bon : tes recos sont prêtes.");
    expect(counterLabel(14, 10)).toBe("C'est bon : tes recos sont prêtes.");
  });
});
