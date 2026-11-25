import { expect, test } from "@playwright/test";

const requests: string[] = [];

function discoveryItem(id: number, title: string, year: number) {
  return {
    provider: "tmdb",
    provider_id: id,
    media_type: "movie",
    title,
    original_title: title,
    year,
    rating: 7.8,
    rating_count: 1200,
    poster_path: null,
    backdrop_path: null,
    genre_ids: [27]
  };
}

async function installDiscoveryApi(page) {
  requests.length = 0;
  await page.route("**/config.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ xiaoyaSearchBaseUrl: "" })
    })
  );
  await page.route("**/api/discovery/discover**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.search);
    const year = url.searchParams.get("year");
    const items = year === "2000"
      ? [discoveryItem(2000, "千禧年恐怖片", 2000)]
      : year === "2020"
        ? [discoveryItem(2020, "近年恐怖片", 2020)]
        : [
            discoveryItem(2020, "近年恐怖片", 2020),
            discoveryItem(2000, "千禧年恐怖片", 2000)
          ];
    return route.fulfill({
      json: {
        provider: "tmdb",
        media_type: "movie",
        page: Number(url.searchParams.get("page") || 1),
        total_pages: 1,
        total_results: items.length,
        items,
        attribution: "TMDB"
      }
    });
  });
}

test("filters the complete horror list by release year and keeps the year in the URL", async ({ page }) => {
  await installDiscoveryApi(page);
  await page.goto("/discover/horror-high");

  await expect(page.getByRole("heading", { name: "恐怖片高分榜" })).toBeVisible();
  await expect(page.getByRole("link", { name: "近年恐怖片", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "千禧年恐怖片", exact: true })).toBeVisible();

  await page.getByLabel("按上映年份筛选").selectOption("2000");
  await expect(page).toHaveURL(/year=2000/);
  await expect(page.getByRole("link", { name: "千禧年恐怖片", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "近年恐怖片", exact: true })).toHaveCount(0);
  expect(requests.some((query) => new URLSearchParams(query).get("year") === "2000")).toBe(true);

  await page.getByLabel("按上映年份筛选").selectOption("");
  await expect(page).not.toHaveURL(/year=/);
  await expect(page.getByRole("link", { name: "近年恐怖片", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "千禧年恐怖片", exact: true })).toBeVisible();
});

test("restores the selected year when navigating browser history", async ({ page }) => {
  await installDiscoveryApi(page);
  await page.goto("/discover/thriller-high?year=2020");

  await expect(page.getByLabel("按上映年份筛选")).toHaveValue("2020");
  await expect(page.getByRole("link", { name: "近年恐怖片", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "千禧年恐怖片", exact: true })).toHaveCount(0);

  await page.getByLabel("按上映年份筛选").selectOption("2000");
  await expect(page.getByLabel("按上映年份筛选")).toHaveValue("2000");
  await page.goBack();
  await expect(page.getByLabel("按上映年份筛选")).toHaveValue("2020");
  await expect(page.getByRole("link", { name: "近年恐怖片", exact: true })).toBeVisible();
  await page.goForward();
  await expect(page.getByLabel("按上映年份筛选")).toHaveValue("2000");
  await expect(page.getByRole("link", { name: "千禧年恐怖片", exact: true })).toBeVisible();
});
