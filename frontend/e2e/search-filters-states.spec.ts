import { expect, test } from "@playwright/test";

const resultMovie = {
  id: 41,
  douban_id: "1292052",
  title: "筛选命中的电影",
  original_title: "Filtered Movie",
  year: 2022,
  rating: 8.7,
  rating_count: 12500,
  type: "movie",
  genres: ["剧情", "科幻"],
  regions: ["中国大陆"],
  updated_at: null
};

const discoveryItem = {
  provider: "tmdb",
  provider_id: 4100,
  media_type: "movie",
  title: "在线匹配影片",
  original_title: "Online Match",
  year: 2022,
  rating: 8.1,
  rating_count: 2500,
  poster_path: null,
  backdrop_path: null,
  genre_ids: [18, 878]
};

async function installOptions(page) {
  await page.route("**/config.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ xiaoyaSearchBaseUrl: "" }) })
  );
  await page.route("**/api/discovery/regions", (route) =>
    route.fulfill({ json: { provider: "tmdb", regions: [{ code: "CN", name: "中国大陆" }, { code: "JP", name: "日本" }] } })
  );
  await page.route("**/api/discovery/genres**", (route) =>
    route.fulfill({ json: { provider: "tmdb", media_type: "movie", genres: [
      { id: 18, name: "剧情" }, { id: 878, name: "科幻" }, { id: 27, name: "恐怖" }
    ] } })
  );
}

test("submits online Discover with dynamic multi-select filters and preserves selections in the URL", async ({ page }) => {
  const localQueries: URLSearchParams[] = [];
  let discoverUrl = "";

  await installOptions(page);
  await page.route("**/api/discovery/discover**", async (route) => {
    discoverUrl = route.request().url();
    await route.fulfill({
      json: { provider: "tmdb", media_type: "movie", page: 1, total_pages: 1,
        total_results: 1, items: [discoveryItem], attribution: "TMDB" }
    });
  });
  await page.route("**/api/movies**", async (route) => {
    const url = new URL(route.request().url());
    localQueries.push(url.searchParams);
    await route.fulfill({ json: { items: [resultMovie], next_cursor: null, total: 1 } });
  });

  await page.goto("/search");
  await page.getByLabel("影视类型").selectOption("movie");
  await page.getByLabel("最低 TMDB 评分").selectOption("8");
  await page.getByLabel("最低投票数").fill("1000");
  await page.getByLabel("起始年份").fill("2020");
  await page.getByLabel("结束年份").fill("2024");
  await page.getByText("类型（可多选）").click();
  await page.getByLabel("搜索类型，例如：恐怖、悬疑…").fill("剧");
  await page.getByLabel("搜索类型，例如：恐怖、悬疑…").fill("");
  await page.getByRole("checkbox", { name: "剧情" }).check();
  await page.getByRole("checkbox", { name: "科幻" }).check();
  await page.getByText("制作国家/地区（可多选）").click();
  await page.getByRole("checkbox", { name: "中国大陆" }).check();
  await page.getByRole("checkbox", { name: "日本" }).check();
  await page.getByRole("button", { name: /搜索/ }).click();

  await expect(page.getByRole("link", { name: "在线匹配影片" })).toBeVisible();
  await expect.poll(() => localQueries.length).toBeGreaterThan(0);
  const local = localQueries.find((query) => query.has("min_rating") && query.has("genres"))!;
  expect(local.get("min_rating")).toBe("8");
  expect(local.get("min_rating_count")).toBe("1000");
  expect(local.get("min_year")).toBe("2020");
  expect(local.get("max_year")).toBe("2024");
  expect(local.get("genres")).toBe("剧情,科幻");
  expect(local.get("regions")).toBe("中国大陆,日本");

  const online = new URL(discoverUrl);
  expect(online.searchParams.get("media_type")).toBe("movie");
  expect(online.searchParams.get("with_genres")).toBe("18,878");
  expect(online.searchParams.get("region")).toBe("CN|JP");
  expect(online.searchParams.get("min_rating")).toBe("8");
  expect(online.searchParams.get("min_votes")).toBe("1000");
  expect(online.searchParams.get("min_year")).toBe("2020");
  expect(online.searchParams.get("max_year")).toBe("2024");

  const pageUrl = new URL(page.url());
  expect(pageUrl.searchParams.get("type")).toBe("movie");
  expect(pageUrl.searchParams.get("genre_ids")).toBe("18,878");
  expect(pageUrl.searchParams.get("region_codes")).toBe("CN|JP");

});

test("shows a useful empty state when online and local discovery return no matches", async ({ page }) => {
  await installOptions(page);
  await page.route("**/api/discovery/search**", (route) =>
    route.fulfill({
      json: { provider: "tmdb", query: "不存在的影片", page: 1, total_pages: 0,
        total_results: 0, items: [], attribution: "TMDB" }
    })
  );
  await page.route("**/api/movies**", (route) =>
    route.fulfill({ json: { items: [], next_cursor: null, total: 0 } })
  );

  await page.goto("/search");
  await page.getByPlaceholder("输入片名，例如：异形、蝙蝠侠…").fill("不存在的影片");
  await page.getByRole("button", { name: /搜索/ }).click();

  await expect(page.getByText("没有找到匹配的作品")).toBeVisible();
});

test("surfaces local API failures without hiding online search results", async ({ page }) => {
  await installOptions(page);
  await page.route("**/api/discovery/search**", (route) =>
    route.fulfill({
      json: { provider: "tmdb", query: "故障", page: 1, total_pages: 0,
        total_results: 0, items: [], attribution: "TMDB" }
    })
  );
  await page.route("**/api/movies**", (route) =>
    route.fulfill({ status: 503, json: { detail: "数据库暂不可用" } })
  );

  await page.goto("/search");
  await page.getByPlaceholder("输入片名，例如：异形、蝙蝠侠…").fill("故障");
  await page.getByRole("button", { name: /搜索/ }).click();

  await expect(page.getByText("数据库暂不可用")).toBeVisible();
  await expect(page.getByText("没有找到匹配的作品")).toBeVisible();
});
