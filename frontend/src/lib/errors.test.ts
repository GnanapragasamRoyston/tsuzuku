import { describe, expect, it } from "vitest";

import { ApiError, messageFor } from "@/lib/errors";

describe("messages d'erreur (ton de DESIGN.md § 7)", () => {
  it("connexion refusée : ne dit pas si c'est l'email ou le mot de passe", () => {
    expect(messageFor(new ApiError(401, "x"), "login")).toBe("Email ou mot de passe incorrect.");
  });

  it("session expirée ailleurs", () => {
    expect(messageFor(new ApiError(401, "Connexion requise"))).toBe(
      "Ta session a expiré. Reconnecte-toi.",
    );
  });

  it("compte déjà existant", () => {
    expect(messageFor(new ApiError(409, "x"), "register")).toBe(
      "Cet email ou ce pseudo est déjà utilisé.",
    );
  });

  it("trop d'essais : durée lisible, arrondie à la minute supérieure", () => {
    expect(messageFor(new ApiError(429, "x", 300))).toBe("Trop d'essais. Réessaie dans 5 minutes.");
    expect(messageFor(new ApiError(429, "x", 42))).toBe("Trop d'essais. Réessaie dans 1 minute.");
    expect(messageFor(new ApiError(429, "x"))).toBe("Trop d'essais. Réessaie dans quelques minutes.");
  });

  it("validation : reprend le message de l'API s'il est rédigé, sinon générique", () => {
    expect(messageFor(new ApiError(422, "choisis au moins 10 œuvres (9 reçues)"))).toBe(
      "Choisis au moins 10 œuvres (9 reçues).",
    );
    expect(messageFor(new ApiError(422, [{ loc: ["body", "email"], msg: "x" }]))).toBe(
      "Vérifie les champs du formulaire.",
    );
  });

  it("service indisponible", () => {
    expect(messageFor(new ApiError(503, "Comptes indisponibles"))).toBe(
      "Tsuzuku est indisponible pour le moment. Réessaie dans un instant.",
    );
  });

  it("problème réseau : selon qu'on enregistre ou qu'on charge", () => {
    expect(messageFor(new TypeError("Failed to fetch"), "save")).toBe(
      "Impossible d'enregistrer. Vérifie ta connexion et réessaie.",
    );
    expect(messageFor(new TypeError("Failed to fetch"))).toBe(
      "Impossible de charger. Vérifie ta connexion et réessaie.",
    );
  });

  it("autres cas", () => {
    expect(messageFor(new ApiError(404, "x"))).toBe("Introuvable.");
    expect(messageFor(new ApiError(500, "x"))).toBe("Une erreur est survenue. Réessaie.");
  });
});
