import { expect, test } from "@playwright/test";

const chart = {
  list_id: 1,
  slug: "top250",
  name: "豆瓣电影 Top 250",
  source: "douban",
  category: "classic",
  period: null,
  description: "经典电影",
  enabled: true,
  display_order: 10,
  last_updated: null
};

const movie = {
  id: 42,
  douban_id: "1292052",
  title: "星际穿越",
  original_title: "Interstellar",
  year: 2014,
  rating: 9.4,
  rating_count: 100000,
  type: "movie",
  genres: ["科幻", "剧情"],
  regions: ["美国"],
  updated_at: null,
  imdb_id: "tt0816692",
  tmdb_id: null,
  directors: ["Christopher Nolan"],
  actors: ["Matthew McConaughey"],
  overview: "A journey through space and time.",
  douban_url: "https://movie.douban.com/subject/1292052/",
  posters: []
};

async function installApiFixtures(page) {
  let favorite = false;

  await page.route("**/config.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        xiaoyaSearchBaseUrl: "https://xiaoya.example/search"
      })
    })
  );

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/charts" && method === "GET") {
      return route.fulfill({ json: [chart] });
    }
    if (path === "/api/charts/top250/snapshots" && method === "GET") {
      return route.fulfill({ json: [] });
    }
    if (path === "/api/charts/top250" && method === "GET") {
      return route.fulfill({
        json: {
          chart,
          items: [{
            ...movie,
            rank: 1,
            source_rating: 9.4,
            snapshot_date: "2026-11-23"
          }],
          next_cursor: null,
          total: 1
        }
      });
    }
    if (path === "/api/movies" && method === "GET") {
      return route.fulfill({
        json: { items: [movie], next_cursor: null, total: 1 }
      });
    }
    if (path === "/api/movies/id/42" && method === "GET") {
      return route.fulfill({ json: movie });
    }
    if (path === "/api/movies/42/poster") {
      return route.fulfill({ status: 404, body: "" });
    }
    if (path === "/api/favorites" && method === "GET") {
      return route.fulfill({
        json: favorite ? [{
          movie,
          created_at: "2026-11-23T00:00:00",
          note: ""
        }] : []
      });
    }
    if (path === "/api/favorites/42" && method === "PUT") {
      favorite = true;
      return route.fulfill({
        json: {
          movie,
          created_at: "2026-11-23T00:00:00",
          note: ""
        }
      });
    }
    if (path === "/api/favorites/42" && method === "DELETE") {
      favorite = false;
      return route.fulfill({ status: 204, body: "" });
    }

    return route.fulfill({
      status: 500,
      json: { detail: `Unexpected fixture request: ${method} ${path}` }
    });
  });
}

test.beforeEach(async ({ page }) => {
  await installApiFixtures(page);
});

test("opens a chart and navigates from its ranked item to movie details", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /豆瓣电影 Top 250/ }).first().click();

  await expect(page.getByRole("heading", { name: "豆瓣电影 Top 250" })).toBeVisible();
  await page.locator("a.movie-title", { hasText: "星际穿越" }).click();

  await expect(page.getByRole("heading", { name: "星际穿越" })).toBeVisible();
  await expect(page.getByText("Interstellar")).toBeVisible();
  await expect(page.getByText("A journey through space and time.")).toBeVisible();
});

test("searches by Chinese title and displays matching movie results", async ({ page }) => {
  await page.goto("/search");
  await page.getByPlaceholder("搜索中文片名或原名…").fill("星际穿越");
  await page.getByRole("button", { name: /搜索电影/ }).click();

  await expect(page.getByRole("link", { name: "星际穿越" }).first()).toBeVisible();
  await expect(page.getByText("1 部作品")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("search")).toBe("星际穿越");
});

test("adds a favorite and opens the configured Xiaoya search in a new tab", async ({ page, context }) => {
  await page.goto("/movies/42");
  await expect(page.getByRole("heading", { name: "星际穿越" })).toBeVisible();

  await page.getByRole("button", { name: "♡ 加入收藏" }).click();
  await expect(page.getByRole("button", { name: "♥ 已收藏" })).toBeVisible();

  const popupPromise = context.waitForEvent("page");
  await page.getByRole("button", { name: /在小雅中搜索/ }).click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL(/https:\/\/xiaoya\.example\/search\?box=/);
  await expect(popup).toHaveURL(/box=%E6%98%9F%E9%99%85%E7%A9%BF%E8%B6%8A/);
});
