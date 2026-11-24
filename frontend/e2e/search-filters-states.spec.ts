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

async function installSearchApi(page, handler: (url: URL) => Promise<void> | void) {
  const requests: string[] = [];
  await page.route("**/config.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ xiaoyaSearchBaseUrl: "" }) })
  );
  await page.route("**/api/movies**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url.search);
    await handler(url);
  });
  return requests;
}

test("submits combined movie filters and preserves every selected condition in the URL", async ({ page }) => {
  const requests = await installSearchApi(page, async (url) => {
    if (url.searchParams.get("genres") === "剧情,科幻") {
      await page.route("**/api/movies**", (route) => route.fulfill({
        json: { items: [resultMovie], next_cursor: null, total: 1 }
      }));
    }
  });

  await page.goto("/search");
  await page.getByLabel("搜索中文片名或原名…").fill("星际");
  await page.getByLabel("影视类型").selectOption("movie");
  await page.getByLabel("最低评分").selectOption("8");
  await page.getByLabel("评价人数不少于").fill("1000");
  await page.getByLabel("起始年份").fill("2020");
  await page.getByLabel("结束年份").fill("2024");
  await page.getByLabel("包含类型").fill("剧情,科幻");
  await page.getByLabel("排除类型").fill("恐怖");
  await page.getByLabel("地区").fill("中国大陆");
  await page.getByLabel("排序依据").selectOption("rating");
  await page.getByLabel("排序方向").selectOption("desc");
  await page.getByRole("button", { name: /搜索电影/ }).click();

  await expect(page.getByRole("link", { name: "筛选命中的电影", exact: true })).toBeVisible();
  await expect.poll(() => requests.some((query) => {
    const p = new URLSearchParams(query);
    return p.get("search") === "星际" &&
      p.get("type") === "movie" &&
      p.get("min_rating") === "8" &&
      p.get("min_rating_count") === "1000" &&
      p.get("min_year") === "2020" &&
      p.get("max_year") === "2024" &&
      p.get("genres") === "剧情,科幻" &&
      p.get("exclude_genres") === "恐怖" &&
      p.get("regions") === "中国大陆" &&
      p.get("sort_by") === "rating" &&
      p.get("sort_order") === "desc";
  })).toBe(true);
});

test("shows a useful empty state when combined filters match no movies", async ({ page }) => {
  await installSearchApi(page, async (url) => {
    await url;
    await page.route("**/api/movies**", (route) => route.fulfill({
      json: { items: [], next_cursor: null, total: 0 }
    }));
  });

  await page.goto("/search");
  await page.getByLabel("搜索中文片名或原名…").fill("不存在的影片");
  await page.getByRole("button", { name: /搜索电影/ }).click();

  await expect(page.getByText("没有找到匹配的电影")).toBeVisible();
  await expect(page.getByText("0 部作品", { exact: true })).toBeVisible();
});

test("surfaces API failures instead of presenting an empty result as success", async ({ page }) => {
  await page.route("**/config.json", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify({ xiaoyaSearchBaseUrl: "" }) })
  );
  await page.route("**/api/movies**", (route) =>
    route.fulfill({ status: 503, json: { detail: "数据库暂不可用" } })
  );

  await page.goto("/search");
  await expect(page.getByText("暂时无法加载")).toBeVisible();
  await expect(page.getByText("数据库暂不可用")).toBeVisible();
});
