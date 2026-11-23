import { describe, expect, it } from "vitest";

import { proxyHeaders } from "@/lib/client-ip";

const SECRET = "secret-de-test";

describe("en-têtes du relais de confiance (ADR 014)", () => {
  it("sur Vercel : secret + première IP de x-forwarded-for (posée par la plateforme)", () => {
    const h = proxyHeaders(new Headers({ "x-forwarded-for": "203.0.113.7, 10.0.0.1" }), {
      secret: SECRET,
      onVercel: true,
    });
    expect(h?.get("x-tsuzuku-proxy")).toBe(SECRET);
    expect(h?.get("x-tsuzuku-client-ip")).toBe("203.0.113.7");
  });

  it("le client ne peut pas imposer son secret ni son IP", () => {
    const forged = new Headers({
      "x-tsuzuku-proxy": "faux",
      "x-tsuzuku-client-ip": "1.2.3.4",
    });
    const h = proxyHeaders(forged, { secret: SECRET, onVercel: false });
    expect(h?.get("x-tsuzuku-proxy")).toBe(SECRET);
    // Hors Vercel, x-forwarded-for vient du client : aucune IP transmise.
    expect(h?.has("x-tsuzuku-client-ip")).toBe(false);
  });

  it("sans secret configuré (dev, tests) : rien à changer", () => {
    expect(proxyHeaders(new Headers(), { secret: undefined, onVercel: false })).toBeNull();
  });
});
