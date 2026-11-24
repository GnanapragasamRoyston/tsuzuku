import { describe, expect, it } from "vitest";

import { cachePolicy } from "@/lib/sw-rules";

const ORIGIN = "https://tsuzuku-eight.vercel.app";
const policy = (path: string, method = "GET", destination = "") =>
  cachePolicy({ url: new URL(path, ORIGIN), method, sameOrigin: true, destination });

describe("règles de cache du service worker (SPEC § 8.1, ADR 015)", () => {
  it("jamais de cache pour l'authentification, les écritures ni l'export RGPD", () => {
    expect(policy("/api/auth/login", "POST")).toBe("network-only");
    expect(policy("/api/auth/logout", "POST")).toBe("network-only");
    expect(policy("/api/me/list/12", "PUT")).toBe("network-only");
    expect(policy("/api/me/list/12", "POST")).toBe("network-only");
    expect(policy("/api/me", "PATCH")).toBe("network-only");
    expect(policy("/api/me/export")).toBe("network-only");
    expect(policy("/api/media/3/cover-suggestions", "POST")).toBe("network-only");
  });

  it("les autres données du compte ne sont pas gardées hors ligne", () => {
    expect(policy("/api/me/recommendations?kind=anime")).toBe("network-only");
    expect(policy("/api/me/drop-risk/12")).toBe("network-only");
  });

  it("« Ma liste » et le compte connecté : cache PRIVÉ (vidé à la déconnexion)", () => {
    expect(policy("/api/me")).toBe("private-api");
    expect(policy("/api/me/list?status=in_progress&limit=100&offset=0")).toBe("private-api");
    expect(policy("/api/me/list/12")).toBe("private-api");
  });

  it("catalogue public : réponse en cache puis rafraîchie", () => {
    expect(policy("/api/media/12")).toBe("public-api");
    expect(policy("/api/media/popular?kind=anime")).toBe("public-api");
    expect(policy("/api/trending")).toBe("public-api");
    expect(policy("/api/users/royston")).toBe("network-only"); // profil : peut repasser en privé
  });

  it("jaquettes, fichiers statiques et pages", () => {
    expect(policy("/_next/image?url=x&w=256&q=75")).toBe("image");
    expect(policy("/_next/static/chunks/app.js")).toBe("static");
    expect(policy("/brand/tsuzuku-icon-192.png")).toBe("static");
    expect(policy("/ma-liste", "GET", "document")).toBe("page");
    expect(policy("/oeuvre/12?_rsc=abc")).toBe("page");
    // Profil public : jamais gardé (un profil repassé en privé doit disparaître tout de suite).
    expect(policy("/profil/royston", "GET", "document")).toBe("network-only");
    expect(policy("/profil/royston?_rsc=abc")).toBe("network-only");
  });

  it("autres origines : le service worker ne s'en mêle pas", () => {
    const other = cachePolicy({
      url: new URL("https://s4.anilist.co/x.jpg"),
      method: "GET",
      sameOrigin: false,
      destination: "image",
    });
    expect(other).toBeNull();
  });
});
