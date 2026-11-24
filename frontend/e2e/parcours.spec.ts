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
  await expect(page.getByRole("link", { name: "J'ai déjà un compte" })).toBeVisible();
  await checkScreen(page, "accueil");
});

test("une page de compte renvoie vers la connexion, avec retour prévu", async ({ page }) => {
  await page.goto("/ma-liste");
  await expect(page).toHaveURL(/\/connexion\?suivant=%2Fma-liste/);
  await checkScreen(page, "connexion");
});

test("inscription → onboarding → recos → ajout → +1 ép. → fiche et note → profil public → Pour toi", async ({ page }) => {
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
  await expect(page.getByRole("tabpanel").getByRole("heading", { name: title })).toBeVisible();
  // Épisode critique = le prochain (ép. 1, vu plus bas sur la fiche) : alerte de la ligne (§ 7).
  await expect(page.getByText(`Prochain épisode : le 1. C'est là que la plupart lâchent ${title}.`)).toBeVisible();
  await checkScreen(page, "ma-liste");

  // 5. +1 épisode : la ligne passe dans « En cours », les compteurs suivent
  await page.getByRole("button", { name: `${title} : +1 épisode` }).click();
  await expect(page.getByRole("tab", { name: /En cours\s*·\s*1/ })).toBeVisible();
  await page.getByRole("tab", { name: /En cours/ }).click();
  await expect(page.getByText("1 / 12 ép.")).toBeVisible();

  // 5 bis. Choisir l'épisode directement (DESIGN.md § 5.2) : barre au clavier, puis champ.
  const slider = page.getByRole("slider", { name: `Épisode atteint, ${title}` });
  await slider.focus();
  for (let i = 0; i < 4; i++) await slider.press("ArrowRight");
  await expect(page.getByText("5 / 12 ép.")).toBeVisible();
  await expect(slider).toHaveAttribute("aria-valuetext", "5 épisodes sur 12");
  // Enregistré une seule fois après la dernière touche : toujours là après rechargement.
  await expect(page.locator("[aria-live=polite]").filter({ hasText: `${title} : 5 / 12 ép.` })).toBeAttached();
  await page.reload();
  await expect(page.getByText("5 / 12 ép.")).toBeVisible();
  await page.getByRole("button", { name: new RegExp(`Changer l'épisode atteint pour ${title}`) }).click();
  const field = page.getByLabel("Épisode atteint", { exact: true });
  await field.fill("13");
  await page.getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Entre un nombre entre 0 et 12." })).toBeVisible();
  await field.fill("8");
  await field.press("Enter");
  await expect(page.getByText("8 / 12 ép.")).toBeVisible();
  // Le focus revient sur le compteur (§ 5.2).
  await expect(page.getByRole("button", { name: new RegExp(`^8 / 12 ép\\. Changer`) })).toBeFocused();
  await checkScreen(page, "ma-liste-progression");

  // 6. Fiche œuvre (phase 9) : le titre mène à la fiche ; risque, courbe, note
  await page.getByRole("link", { name: title }).first().click();
  await expect(page).toHaveURL(/\/oeuvre\/\d+$/);
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ton risque de drop" })).toBeVisible();
  await expect(page.getByText(/^(À risque|Risque faible|Pas encore assez de données)$/)).toBeVisible();
  await expect(page.getByText("Épisode 1 — critique.", { exact: false })).toBeVisible();
  await expect(page.getByText("Dans ta liste :", { exact: false })).toBeVisible();
  // On clique le segment (le libellé), comme une personne : la case radio est masquée dessous.
  const eight = page.getByRole("radio", { name: `8 sur 10 pour ${title}` });
  await page.locator("label").filter({ has: eight }).click();
  await expect(eight).toBeChecked();
  await expect(page.getByText("8/10", { exact: true })).toBeVisible();

  // Proposer une jaquette : adresse hors liste refusée, adresse AniList mise en file de modération
  await page.getByRole("button", { name: "Proposer une jaquette" }).click();
  const coverUrl = page.getByLabel("Adresse de l'image");
  await coverUrl.fill("https://exemple.test/image.jpg");
  await page.getByRole("button", { name: "Envoyer" }).click();
  await expect(page.getByText(/Adresse refusée/)).toBeVisible();
  await coverUrl.fill("https://s4.anilist.co/file/anilistcdn/media/anime/cover/large/bx1-e2e.jpg");
  await page.getByRole("button", { name: "Envoyer" }).click();
  await expect(page.getByRole("status").filter({ hasText: "on la vérifie" })).toBeVisible();
  // Dans le même esprit (phase 10) : voisins par le contenu, en fin de fiche
  const sameSpirit = page.getByRole("region", { name: "Dans le même esprit" });
  await expect(sameSpirit.getByRole("link").first()).toBeVisible();
  await checkScreen(page, "fiche");

  // 7. Profil public : privé par défaut, ouvert depuis Compte, la note y apparaît
  await page.goto("/compte");
  await page.getByLabel("Rendre mon profil public").check();
  await page.getByRole("link", { name: "Voir mon profil public" }).click();
  await expect(page).toHaveURL(new RegExp(`/profil/${pseudo}$`));
  await expect(page.getByRole("heading", { level: 1, name: pseudo })).toBeVisible();
  await expect(page.getByRole("link", { name: title })).toBeVisible();
  await expect(page.getByText("8/10", { exact: true })).toBeVisible();
  await checkScreen(page, "profil");

  // 8. Pour toi en page entière
  await page.goto("/pour-toi");
  await expect(page.getByRole("heading", { level: 1, name: "Pour toi" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Mangas et manhwas" })).toBeVisible();
  // Recos par le contenu (phase 10) : le profil d'animes « action » fait remonter le manhwa
  // « action », avec la raison cross-média.
  const manhwas = page.getByRole("list", { name: "Manhwas et manhuas" });
  await expect(manhwas.getByRole("link", { name: "Manhwa de test" })).toBeVisible();
  await expect(manhwas.getByText(/Parce que tu as aimé Anime de test/).first()).toBeVisible();
  await checkScreen(page, "pour-toi");

  // 9. Retour à l'accueil connecté : plus de « J'ai déjà un compte » (bug de prod du 2026-11-24,
  // la personne se croyait déconnectée), mais ses recos et sa liste.
  await page.getByRole("link", { name: "Tsuzuku, accueil" }).click();
  await expect(page.getByRole("link", { name: "Voir mes recos" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("link", { name: "Ma liste" })).toBeVisible();
  await expect(page.getByRole("link", { name: "J'ai déjà un compte" })).toHaveCount(0);
});

test("un profil privé ou inconnu est introuvable, comme une page qui n'existe pas", async ({ page }) => {
  await page.goto("/profil/personne_ici");
  await expect(page.getByRole("heading", { name: "Page introuvable" })).toBeVisible();
  await page.goto("/oeuvre/999999");
  await expect(page.getByRole("heading", { name: "Page introuvable" })).toBeVisible();
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


test("PWA : installable, et « Ma liste » reste lisible hors ligne (phase 12)", async ({ page, context }) => {
  const manifest = await (await page.request.get("/manifest.webmanifest")).json();
  expect(manifest).toMatchObject({ display: "standalone", scope: "/", id: "/" });
  expect(manifest.icons.some((i: { purpose?: string }) => i.purpose === "maskable")).toBe(true);

  const pseudo = `pwa_${Date.now().toString(36)}`;
  await page.goto("/inscription");
  await page.getByLabel("Email").fill(`${pseudo}@example.com`);
  await page.getByLabel("Pseudo").fill(pseudo);
  await page.getByLabel("Mot de passe").fill("une phrase de passe solide");
  await page.getByRole("button", { name: "Créer mon compte" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  for (const n of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) {
    await page.getByRole("button", { name: new RegExp(`Anime de test ${String(n).padStart(2, "0")}`) }).click();
  }
  await page.getByRole("button", { name: "Voir mes recos" }).click();
  await expect(page).toHaveURL(/\/ma-liste$/);
  // Le service worker contrôle la page, puis « Ma liste » est rechargée en ligne (cache rempli).
  await page.evaluate(async () => (await navigator.serviceWorker.ready).active?.state);
  await page.reload();
  await page.getByRole("button", { name: /^Ajouter .* à ma liste$/ }).first().click();
  await page.getByRole("tab", { name: /Prévu/ }).click();
  await expect(page.getByRole("tabpanel").getByRole("heading").first()).toBeVisible();

  await context.setOffline(true);
  await page.reload();
  await expect(page.getByRole("status").filter({ hasText: "Hors ligne." })).toBeVisible();
  await page.getByRole("tab", { name: /Prévu/ }).click();
  await expect(page.getByRole("tabpanel").getByRole("heading").first()).toBeVisible();
  // Une page jamais ouverte : la page de secours.
  await page.goto("/confidentialite");
  await expect(page.getByRole("heading", { name: "Pas de réseau" })).toBeVisible();
  await context.setOffline(false);

  // Déconnexion : le cache privé du service worker est vidé (téléphone partagé).
  await page.goto("/compte");
  await page.getByRole("button", { name: "Me déconnecter" }).click();
  // Déconnecté (accueil, ou connexion si la page Compte voit la session disparaître d'abord).
  await expect(page.getByRole("link", { name: "Connexion" }).first()).toBeVisible();
  expect(await page.evaluate(() => caches.has("tsuzuku-private"))).toBe(false);
});
