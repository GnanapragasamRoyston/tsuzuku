/**
 * Parcours clé (SPEC § 8, PROMPT_DESIGN étape 2) : inscription → onboarding → recos → ajout à la
 * liste → progression. Chaque écran passe aussi axe-core (accessibilité, contrastes compris) et
 * laisse des captures à 375 et 1440 px dans test-results/captures pour la relecture visuelle.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const WIDTHS = [375, 1440] as const;

async function checkScreen(page: Page, name: string) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa", "best-practice"]).analyze();
  expect(
    results.violations.map(
      (v) => `${v.id}: ${v.help} → ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`,
    ),
  ).toEqual([]);
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 900 });
    // Aucun débordement horizontal (bug corrigé sur Ma liste en mobile).
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: `test-results/captures/${name}-${width}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test("un visiteur voit l'accueil, avec le catalogue de l'API", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Note ce que tu regardes");
  await expect(page.getByText("Anime de test 01").first()).toBeVisible();
  await checkScreen(page, "accueil");
});

test("une page de compte renvoie vers la connexion, avec retour prévu", async ({ page }) => {
  await page.goto("/ma-liste");
  await expect(page).toHaveURL(/\/connexion\?suivant=%2Fma-liste/);
  await checkScreen(page, "connexion");
});

test("inscription → onboarding → recos → ajout à la liste → +1 épisode", async ({ page }) => {
  const pseudo = `e2e_${Date.now().toString(36)}`;

  // 1. Inscription
  await page.goto("/inscription");
  await checkScreen(page, "inscription");
  await page.getByLabel("Email").fill(`${pseudo}@example.com`);
  await page.getByLabel("Pseudo").fill(pseudo);
  await page.getByLabel("Mot de passe").fill("une phrase de passe solide");
  await page.getByRole("button", { name: "Créer mon compte" }).click();

  // 2. Onboarding : 10 animes du groupe « action » (1 à 8) et 2 autres
  await expect(page).toHaveURL(/\/onboarding$/);
  const submit = page.getByRole("button", { name: "Voir mes recos" });
  await expect(submit).toBeDisabled();
  for (const n of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) {
    await page.getByRole("button", { name: new RegExp(`Anime de test ${String(n).padStart(2, "0")}`) }).click();
  }
  await expect(page.getByText("C'est bon : tes recos sont prêtes.")).toBeVisible();
  await checkScreen(page, "onboarding");
  await submit.click();

  // 3. Recos personnalisées (ALS : au moins 5 titres aimés)
  await expect(page).toHaveURL(/\/ma-liste$/);
  const forYou = page.getByRole("complementary", { name: "Pour toi" });
  await expect(forYou.getByText(/Calculé à partir des 10 animes/)).toBeVisible();
  const firstReco = forYou.getByRole("button", { name: /^Ajouter .* à ma liste$/ }).first();
  const label = (await firstReco.getAttribute("aria-label")) ?? "";
  const title = label.replace(/^Ajouter /, "").replace(/ à ma liste$/, "");

  // 4. Ajout à la liste (en « Prévu »)
  await firstReco.click();
  // Le bouton reste en place (le focus ne se perd pas) et annonce l'ajout.
  await expect(forYou.getByRole("button", { name: `${title} : dans ta liste` })).toBeVisible();
  await page.getByRole("tab", { name: /Prévu/ }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await checkScreen(page, "ma-liste");

  // 5. +1 épisode : la ligne passe dans « En cours », les compteurs suivent
  await page.getByRole("button", { name: `${title} : +1 épisode` }).click();
  await expect(page.getByRole("tab", { name: /En cours\s*·\s*1/ })).toBeVisible();
  await page.getByRole("tab", { name: /En cours/ }).click();
  await expect(page.getByText("1 / 12 ép.")).toBeVisible();
});

test("connexion refusée : message neutre, sans dire ce qui est faux", async ({ page }) => {
  await page.goto("/connexion");
  await page.getByLabel("Email").fill("personne@example.com");
  await page.getByLabel("Mot de passe").fill("mauvais mot de passe");
  await page.getByRole("button", { name: "Me connecter" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveText(
    "Email ou mot de passe incorrect.",
  );
});
