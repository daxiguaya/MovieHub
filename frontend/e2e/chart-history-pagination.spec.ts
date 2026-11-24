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

function movie(id: number, title: string) {
  return {
    id,
    douban_id: String(10000 + id),
    title,
    original_title: null,
    year: 2020,
    rating: 8.5,
    rating_count: 1000,
    type: "movie",
    genres: ["剧情"],
    regions: ["中国"],
    updated_at: null
  };
}

const snapshots = [
  { snapshot_date: "2026-11-24", imported_at: "2026-11-24T00:00:00", item_count: 3 },
  { snapshot_date: "2026-11-23", imported_at: "2026-11-23T00:00:00", item_count: 2 }
];

async function installChartApi(page) {
  const requests: string[] = [];

  await page.route("**/config.json", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ xiaoyaSearchBaseUrl: "" })
    })
  );

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    requests.push(`${path}${url.search}`);

    if (path === "/api/charts" && request.method() === "GET") {
      return route.fulfill({ json: [chart] });
    }

    if (path === "/api/charts/top250/snapshots") {
      return route.fulfill({ json: snapshots });
    }

    if (path === "/api/charts/top250" && request.method() === "GET") {
      const date = url.searchParams.get("snapshot_date");
      const cursor = url.searchParams.get("cursor");

      if (date === "2026-11-23") {
        return route.fulfill({
          json: {
            chart,
            items: [{ ...movie(11, "历史快照电影"), rank: 1, source_rating: 8.1, snapshot_date: date }],
            next_cursor: null,
            total: 2
          }
        });
      }

      if (cursor === "page-2") {
        return route.fulfill({
          json: {
            chart,
            items: [{ ...movie(3, "第三部电影"), rank: 3, source_rating: 8.3, snapshot_date: "2026-11-24" }],
            next_cursor: null,
            total: 3
          }
        });
      }

      return route.fulfill({
        json: {
          chart,
          items: [
            { ...movie(1, "第一页电影"), rank: 1, source_rating: 8.5, snapshot_date: "2026-11-24" },
            { ...movie(2, "第二部电影"), rank: 2, source_rating: 8.4, snapshot_date: "2026-11-24" }
          ],
          next_cursor: "page-2",
          total: 3
        }
      });
    }

    if (path === "/api/charts/top250/compare") {
      return route.fulfill({
        json: {
          chart,
          from_date: "2026-11-23",
          to_date: "2026-11-24",
          total_before: 2,
          total_after: 3,
          items: [
            {
              movie_id: 1,
              douban_id: "10001",
              title: "第一页电影",
              year: 2020,
              type: "movie",
              before_rank: 2,
              after_rank: 1,
              rank_change: 1,
              status: "moved"
            },
            {
              movie_id: 3,
              douban_id: "10003",
              title: "第三部电影",
              year: 2020,
              type: "movie",
              before_rank: null,
              after_rank: 3,
              rank_change: null,
              status: "new"
            }
          ]
        }
      });
    }

    return route.fulfill({
      status: 500,
      json: { detail: `Unexpected fixture request: ${request.method()} ${path}` }
    });
  });

  return requests;
}

test("paginates a chart to its last page without losing the first page", async ({ page }) => {
  const requests = await installChartApi(page);

  await page.goto("/charts/top250");
  await expect(page.getByRole("heading", { name: "豆瓣电影 Top 250" })).toBeVisible();
  await expect(page.getByText("3 部作品", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "第一页电影", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "第二部电影", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "加载更多" }).click();
  await expect(page.getByRole("link", { name: "第三部电影", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "第一页电影", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "加载更多" })).toHaveCount(0);
  expect(requests.some((request) => request.includes("cursor=page-2"))).toBe(true);
});

test("switches to a historical snapshot and resets the visible page", async ({ page }) => {
  const requests = await installChartApi(page);

  await page.goto("/charts/top250");
  await expect(page.getByRole("link", { name: "第一页电影", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "加载更多" }).click();
  await expect(page.getByRole("link", { name: "第三部电影", exact: true })).toBeVisible();

  await page.getByLabel("历史日期").selectOption("2026-11-23");
  await expect(page.getByRole("link", { name: "历史快照电影", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "第一页电影", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "第三部电影", exact: true })).toHaveCount(0);
  await expect(page.getByText("2 部作品", { exact: true })).toBeVisible();
  expect(requests.some((request) => request.includes("snapshot_date=2026-11-23"))).toBe(true);
});

test("compares two dated snapshots and displays rank movement and new entries", async ({ page }) => {
  await installChartApi(page);

  await page.goto("/charts/top250");
  await expect(page.getByRole("heading", { name: "豆瓣电影 Top 250" })).toBeVisible();
  await page.getByRole("button", { name: "比较排名" }).click();

  await expect(page.getByText("第一页电影", { exact: true })).toBeVisible();
  await expect(page.getByText("排名变动 · ↑1")).toBeVisible();
  await expect(page.getByText("新上榜")).toBeVisible();
});
