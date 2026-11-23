import { defineConfig, devices } from "@playwright/test";

/*
 * Tests de bout en bout (phase 8) : vraie API (base tsuzuku_e2e, mini catalogue et mini modèles,
 * backend/scripts/e2e_api.py) + front en build de production (next build && next start).
 * Ports dédiés (8001, 3001) : n'interfère pas avec make api / make web.
 */
const API_PORT = 8001;
const WEB_PORT = 3001;

// Secret de test seulement (jamais celui de la production).
const PROXY_SECRET = "e2e-relais-de-confiance-pas-pour-la-production";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1, // une seule base partagée : les parcours s'enchaînent
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  timeout: 60_000,
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    locale: "fr-FR",
    trace: "retain-on-failure",
    // Mouvement réduit (respecté par globals.css) : transitions à 0 ms, donc axe mesure les
    // couleurs finales et non une étape de transition.
    contextOptions: { reducedMotion: "reduce" },
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "uv run python scripts/e2e_api.py",
      cwd: "../backend",
      // Relais de confiance actif comme en production (ADR 014) : si Next ne transmettait pas
      // ses en-têtes à travers la réécriture /api/*, chaque appel prendrait un 403.
      env: { E2E_PROXY_SECRET: PROXY_SECRET },
      url: `http://127.0.0.1:${API_PORT}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `npx next build && npx next start --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      timeout: 300_000,
      reuseExistingServer: false,
      env: {
        API_URL: `http://127.0.0.1:${API_PORT}`,
        NEXT_TELEMETRY_DISABLED: "1",
        PROXY_SECRET,
      },
    },
  ],
});
