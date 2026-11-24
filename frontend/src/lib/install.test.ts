import { describe, expect, it } from "vitest";

import { detectPlatform, shouldOfferInstall } from "@/lib/install";

const DAY = 24 * 3600 * 1000;
const NOW = Date.UTC(2026, 10, 24);
const base = { standalone: false, usefulAction: true, dismissedAt: null, now: NOW };

describe("plateforme (invitation à installer, DESIGN.md § 5.10)", () => {
  it("iPhone et iPad (y compris iPad « bureau ») : guide manuel", () => {
    expect(detectPlatform("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari", 5)).toBe("ios");
    expect(detectPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari", 5)).toBe("ios");
  });

  it("Android et ordinateur : invite du navigateur (beforeinstallprompt)", () => {
    expect(detectPlatform("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", 5)).toBe("prompt");
    expect(detectPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari", 0)).toBe("prompt");
  });
});

describe("quand proposer l'installation", () => {
  it("après une action utile, jamais à la première visite", () => {
    expect(shouldOfferInstall(base)).toBe(true);
    expect(shouldOfferInstall({ ...base, usefulAction: false })).toBe(false);
  });

  it("jamais si l'appli est déjà installée", () => {
    expect(shouldOfferInstall({ ...base, standalone: true })).toBe(false);
  });

  it("« Plus tard » masque l'invitation 14 jours", () => {
    expect(shouldOfferInstall({ ...base, dismissedAt: NOW - 3 * DAY })).toBe(false);
    expect(shouldOfferInstall({ ...base, dismissedAt: NOW - 15 * DAY })).toBe(true);
  });
});
