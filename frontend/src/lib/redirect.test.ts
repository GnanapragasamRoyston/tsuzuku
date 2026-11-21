import { describe, expect, it } from "vitest";

import { safeNext } from "@/lib/redirect";

describe("retour après connexion (?suivant=)", () => {
  it("accepte un chemin interne", () => {
    expect(safeNext("/ma-liste", "/")).toBe("/ma-liste");
    expect(safeNext("/onboarding?etape=2", "/")).toBe("/onboarding?etape=2");
  });

  it.each([
    "https://evil.example/",
    "//evil.example",
    "/\\evil.example",
    "javascript:alert(1)",
    "ma-liste",
    "",
    // Le navigateur retire tabulations et sauts de ligne en analysant l'URL : « /\t/hote » devient
    // « //hote », donc un autre site (revue de sécurité, phase 8).
    "/\t/evil.example",
    "/\n/evil.example",
    "/\r/evil.example",
    decodeURIComponent("/%09/evil.example"),
  ])("refuse %j (redirection ouverte) et renvoie la valeur par défaut", (value) => {
    expect(safeNext(value, "/ma-liste")).toBe("/ma-liste");
  });

  it("absent : valeur par défaut", () => {
    expect(safeNext(null, "/ma-liste")).toBe("/ma-liste");
  });
});
