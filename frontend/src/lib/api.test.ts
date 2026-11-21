import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api";
import { ApiError } from "@/lib/errors";

function mockFetch(response: Response) {
  const fn = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("client API (navigateur)", () => {
  it("passe par le relais /api du front et envoie du JSON", async () => {
    const fetch = mockFetch(Response.json({ count: 10 }));
    const body = await apiFetch<{ count: number }>("/me/onboarding", {
      method: "POST", body: { media_ids: [1, 2] },
    });
    expect(body).toEqual({ count: 10 });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/me/onboarding");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ media_ids: [1, 2] }));
    // Même origine : le cookie de session part tout seul, sans credentials « include ».
    expect(init.credentials).toBe("same-origin");
  });

  it("204 : renvoie null", async () => {
    mockFetch(new Response(null, { status: 204 }));
    expect(await apiFetch("/auth/logout", { method: "POST" })).toBeNull();
  });

  it("erreur : ApiError avec statut, détail et Retry-After", async () => {
    mockFetch(Response.json({ detail: "Trop de tentatives" },
                            { status: 429, headers: { "Retry-After": "300" } }));
    const error = await apiFetch("/auth/login", { method: "POST", body: {} }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 429, detail: "Trop de tentatives", retryAfter: 300 });
  });

  it("erreur sans corps JSON (proxy, page HTML) : ApiError quand même", async () => {
    mockFetch(new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(apiFetch("/media/popular")).rejects.toMatchObject({ status: 502, detail: null });
  });
});
