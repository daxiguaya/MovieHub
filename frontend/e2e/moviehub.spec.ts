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

const discoveryItem = {
  provider: "tmdb",
  provider_id: 999,
  media_type: "movie",
  title: "星际穿越",
  original_title: "Interstellar",
  year: 2014,
  rating: 8.7,
  rating_count: 1000,
  poster_path: null,
  backdrop_path: null,
  genre_ids: [878]
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

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/config" && method === "GET") {
      return route.fulfill({
        json: {
          xiaoyaSearchUrlTemplate: "https://xiaoya.example/search?box={query}&type=video&url="
        }
      });
    }
    if (path === "/api/discovery/regions" && method === "GET") {
      return route.fulfill({ json: { provider: "tmdb", regions: [{ code: "US", name: "美国" }] } });
    }
    if (path === "/api/discovery/genres" && method === "GET") {
      return route.fulfill({ json: { provider: "tmdb", media_type: "movie", genres: [{ id: 878, name: "科幻" }] } });
    }
    if (path === "/api/discovery/search" && method === "GET") {
      return route.fulfill({
        json: { provider: "tmdb", query: url.searchParams.get("q"), page: 1, total_pages: 1,
          total_results: 1, items: [discoveryItem], attribution: "TMDB" }
      });
    }
    if (path === "/api/discovery/discover" && method === "GET") {
      const requestedPage = Number(url.searchParams.get("page") ?? "1");
      return route.fulfill({
        json: { provider: "tmdb", media_type: "movie", page: requestedPage, total_pages: 2,
          total_results: 25, items: [{ ...discoveryItem, provider_id: 999 + requestedPage,
            title: requestedPage === 1 ? "专题第一页作品" : "专题第二页作品" }], attribution: "TMDB" }
      });
    }
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

test("shows prominent horror and thriller lists and loads their pages on demand", async ({ page }) => {
  const requestedPages: string[] = [];
  await page.route("**/api/discovery/discover**", async (route) => {
    const url = new URL(route.request().url());
    requestedPages.push(url.searchParams.get("page") ?? "1");
    const requestedPage = Number(url.searchParams.get("page") ?? "1");
    await route.fulfill({
      json: { provider: "tmdb", media_type: "movie", page: requestedPage, total_pages: 2,
        total_results: 25, items: [{ ...discoveryItem, provider_id: 9000 + requestedPage,
          title: requestedPage === 1 ? "恐怖榜单首屏作品" : "恐怖榜单第二页作品" }], attribution: "TMDB" }
    });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "恐怖与惊悚专题" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "恐怖片高分榜" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "惊悚片冷门佳作" })).toBeVisible();
  await page.getByRole("link", { name: "查看完整榜单" }).first().click();

  await expect(page.getByRole("heading", { name: "恐怖片高分榜" })).toBeVisible();
  await expect(page.getByRole("link", { name: "恐怖榜单首屏作品" }).first()).toBeVisible();
  expect(requestedPages).not.toContain("2");

  await page.getByRole("button", { name: "加载下一页" }).click();
  await expect(page.getByRole("link", { name: "恐怖榜单第二页作品" })).toBeVisible();
  expect(requestedPages).toContain("2");
});

test("searches by Chinese title and displays matching movie results", async ({ page }) => {
  await page.goto("/search");
  await page.getByPlaceholder("输入片名，例如：异形、蝙蝠侠…").fill("星际穿越");
  await page.getByRole("button", { name: /搜索/ }).click();

  await expect(page.getByRole("link", { name: "星际穿越" }).first()).toBeVisible();
  await expect(page.getByText(/1 部 · 本地匹配 1 部/)).toBeVisible();
  expect(new URL(page.url()).searchParams.get("search")).toBe("星际穿越");
});

test("adds a favorite and opens the configured Xiaoya search in a new tab", async ({ page, context }) => {
  await page.goto("/movies/42");
  await expect(page.getByRole("heading", { name: "星际穿越" })).toBeVisible();

  await page.getByRole("button", { name: "♡ 加入收藏" }).click();
  await expect(page.getByRole("button", { name: "♥ 已收藏" })).toBeVisible();

  await context.route("https://xiaoya.example/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<title>Xiaoya handoff fixture</title>"
    })
  );
  const popupPromise = context.waitForEvent("page");
  await page.getByRole("button", { name: /在小雅中搜索/ }).click();
  const popup = await popupPromise;
  await expect(popup).toHaveURL(/https:\/\/xiaoya\.example\/search\?box=/);
  expect(new URL(popup.url()).searchParams.get("box")).toBe("星际穿越");
  await expect(popup).toHaveTitle("Xiaoya handoff fixture");
});


test("connects the browser to the real FastAPI service and temporary SQLite database", async ({ page }) => {
  // This test deliberately removes the API fixture installed by beforeEach.
  // The dedicated CI job starts a real FastAPI process backed by a temporary DB.
  await page.unroute("**/api/**");

  await page.goto("/");
  await page.locator('a.chart-tile[href="/charts/top250"]').click();
  await expect(page.getByRole("heading", { name: "豆瓣电影 Top 250" })).toBeVisible();
  await expect(page.locator("a.movie-title", { hasText: "星际穿越" })).toBeVisible();

  await page.locator("a.movie-title", { hasText: "星际穿越" }).click();
  await expect(page.getByRole("heading", { name: "星际穿越" })).toBeVisible();
  await expect(page.getByText("A journey through space and time.")).toBeVisible();

  await page.goto("/search");
  await page.getByPlaceholder("输入片名，例如：异形、蝙蝠侠…").fill("星际穿越");
  await page.getByRole("button", { name: /搜索/ }).click();
  await expect(page.locator("a.movie-title", { hasText: "星际穿越" })).toBeVisible();
});

test("real 2025 annual snapshots render through the live API and support detail/search navigation", async ({ page }) => {
  test.skip(
    process.env.MOVIEHUB_REAL_ANNUAL_E2E !== "1",
    "requires the dedicated CI job with imported official annual snapshots"
  );

  // The dedicated CI job imports the retained official 2025 artifact into a
  // disposable SQLite database and starts the real FastAPI service.
  await page.unroute("**/api/**");

  const annualCharts = [
    { slug: "annual-2025-chinese-movies", name: "2025 评分最高华语电影", count: 8 },
    { slug: "annual-2025-international-movies", name: "2025 评分最高外语电影", count: 10 },
    { slug: "annual-2025-hidden-gems", name: "2025 年度冷门佳片", count: 10 },
    { slug: "annual-2025-chinese-tv", name: "2025 评分最高华语剧集", count: 10 }
  ];

  for (const chart of annualCharts) {
    await page.goto("/");
    await page.locator(`a.chart-tile[href="/charts/${chart.slug}"]`).click();
    await expect(page.getByRole("heading", { name: chart.name })).toBeVisible();
    await expect(page.getByText(`${chart.count} 部作品`, { exact: true })).toBeVisible();
    await expect(page.locator("a.movie-title").first()).toBeVisible();
  }

  // Follow one real imported record through its detail page and title search.
  await page.goto("/charts/annual-2025-chinese-movies");
  const firstMovie = page.locator("a.movie-title").first();
  await expect(firstMovie).toBeVisible();
  const title = (await firstMovie.innerText()).trim();
  expect(title.length).toBeGreaterThan(0);
  await firstMovie.click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();

  await page.goto("/search");
  await page.getByPlaceholder("输入片名，例如：异形、蝙蝠侠…").fill(title);
  await page.getByRole("button", { name: /搜索/ }).click();
  await expect(page.locator("a.movie-title", { hasText: title }).first()).toBeVisible();
});

test("real Top 250 first-launch snapshot renders through the live API and supports detail/search navigation", async ({ page }) => {
  test.skip(
    process.env.MOVIEHUB_REAL_ANNUAL_E2E !== "1",
    "requires the dedicated CI job with the combined first-launch dataset"
  );

  await page.unroute("**/api/**");
  await page.goto("/");
  await page.locator('a.chart-tile[href="/charts/top250"]').click();
  await expect(page.getByRole("heading", { name: "豆瓣电影 Top 250" })).toBeVisible();
  await expect(page.getByText("250 部作品", { exact: true })).toBeVisible();

  const firstMovie = page.locator("a.movie-title").first();
  await expect(firstMovie).toBeVisible();
  const title = (await firstMovie.innerText()).trim();
  expect(title.length).toBeGreaterThan(0);
  await firstMovie.click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();

  await page.goto("/search");
  await page.getByPlaceholder("输入片名，例如：异形、蝙蝠侠…").fill(title);
  await page.getByRole("button", { name: /搜索/ }).click();
  await expect(page.locator("a.movie-title", { hasText: title }).first()).toBeVisible();
});

test("real first-launch dataset remains usable on a narrow mobile viewport", async ({ page }) => {
  test.skip(
    process.env.MOVIEHUB_REAL_ANNUAL_E2E !== "1",
    "requires the dedicated CI job with the combined first-launch dataset"
  );

  await page.unroute("**/api/**");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/charts/top250");

  await expect(page.getByRole("heading", { name: "豆瓣电影 Top 250" })).toBeVisible();
  await expect(page.getByText("250 部作品", { exact: true })).toBeVisible();
  await expect(page.locator("a.movie-title").first()).toBeVisible();

  const chartOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth
  );
  expect(chartOverflow, "Top 250 chart should not overflow a 390px viewport").toBe(false);

  const firstMovie = page.locator("a.movie-title").first();
  const title = (await firstMovie.innerText()).trim();
  await firstMovie.click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();

  const detailOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth
  );
  expect(detailOverflow, "movie detail should not overflow a 390px viewport").toBe(false);

  await page.goto("/search");
  await page.getByPlaceholder("输入片名，例如：异形、蝙蝠侠…").fill(title);
  await page.getByRole("button", { name: /搜索/ }).click();
  await expect(page.locator("a.movie-title", { hasText: title }).first()).toBeVisible();

  const searchOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth
  );
  expect(searchOverflow, "search results should not overflow a 390px viewport").toBe(false);
});

test("real imported Top 250 movie can be favorited and removed through the live API", async ({ page }) => {
  test.skip(
    process.env.MOVIEHUB_REAL_ANNUAL_E2E !== "1",
    "requires the dedicated CI job with the combined first-launch dataset"
  );

  // The production reverse proxy injects this server-side key for /api/favorites.
  // Emulate that trusted proxy boundary without exposing a key to application code.
  await page.unroute("**/api/**");
  const proxyApiKey = process.env.MOVIEHUB_E2E_PROXY_API_KEY;
  if (!proxyApiKey) {
    throw new Error("MOVIEHUB_E2E_PROXY_API_KEY must be set by the isolated CI job");
  }
  await page.route("**/api/favorites**", (route) =>
    route.continue({
      headers: {
        ...route.request().headers(),
        "x-api-key": proxyApiKey
      }
    })
  );

  await page.goto("/charts/top250");
  const firstMovie = page.locator("a.movie-title").first();
  await expect(firstMovie).toBeVisible();
  const title = (await firstMovie.innerText()).trim();
  await firstMovie.click();

  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await page.getByRole("button", { name: "♡ 加入收藏" }).click();
  await expect(page.getByRole("button", { name: "♥ 已收藏" })).toBeVisible();

  await page.goto("/favorites");
  await expect(page.getByRole("heading", { name: "我的收藏" })).toBeVisible();
  await expect(page.locator("a.movie-title", { hasText: title })).toBeVisible();

  await page.getByRole("button", { name: "移出收藏 ×" }).click();
  await expect(page.getByText("收藏夹还是空的")).toBeVisible();
});
test("shows TMDB attribution and source credits in the dedicated credits section", async ({ page }) => {
  await page.goto("/credits");
  await expect(page.getByRole("heading", { name: "关于与数据来源" })).toBeVisible();
  await expect(page.getByRole("img", { name: "The Movie Database (TMDB)" })).toBeVisible();
  await expect(page.getByText("This product uses the TMDB API but is not endorsed or certified by TMDB.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Visit The Movie Database" })).toHaveAttribute("href", "https://www.themoviedb.org");
});

