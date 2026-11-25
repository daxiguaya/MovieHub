import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter } from "react-router-dom";
import App from "./App";

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload
  } as Response;
}

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

function installFetchMock(handler: (url: string, init?: RequestInit) => unknown) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    jsonResponse(handler(String(input), init))
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.removeItem("moviehubApiKey");
  window.sessionStorage.removeItem("moviehubApiKey");
});

describe("MovieHub frontend workflows", () => {
  it("loads chart collections and navigates to a dated chart page", async () => {
    const fetchMock = installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url === "/api/charts") return [chart];
      if (url.includes("/api/charts/top250/snapshots")) return [];
      if (url === "/api/charts/top250") {
        return { chart, items: [], next_cursor: null, total: 0 };
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    const titles = await screen.findAllByText("豆瓣电影 Top 250");
    await userEvent.click(titles[0].closest("a")!);

    expect(
      await screen.findByRole("heading", { name: "豆瓣电影 Top 250" })
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/charts/top250",
      expect.objectContaining({ headers: expect.any(Object) })
    );
  });

  it("searches the online catalog and uses dynamic multi-select genre and region filters", async () => {
    const fetchMock = installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url === "/api/discovery/regions") {
        return { provider: "tmdb", regions: [{ code: "US", name: "美国" }] };
      }
      if (url.includes("/api/discovery/genres")) {
        return { provider: "tmdb", media_type: "movie", genres: [{ id: 878, name: "科幻" }] };
      }
      if (url.startsWith("/api/discovery/search?")) {
        return {
          provider: "tmdb", query: "星际穿越", page: 1, total_pages: 1,
          total_results: 1, items: [], attribution: "TMDB"
        };
      }
      if (url.startsWith("/api/movies?")) {
        return { items: [], next_cursor: null, total: 0 };
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/search"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByText("在线搜索结果");
    await userEvent.type(
      screen.getByPlaceholderText("输入片名，例如：异形、蝙蝠侠…"),
      "星际穿越"
    );
    await userEvent.selectOptions(screen.getByLabelText("影视类型"), "movie");
    await userEvent.type(screen.getByLabelText("起始年份"), "2010");
    await userEvent.type(screen.getByLabelText("结束年份"), "2020");
    await userEvent.click(screen.getByText("类型（可多选）"));
    await userEvent.click(await screen.findByRole("checkbox", { name: "科幻" }));
    await userEvent.click(screen.getByText("制作国家/地区（可多选）"));
    await userEvent.click(await screen.findByRole("checkbox", { name: "美国" }));
    await userEvent.click(screen.getByRole("button", { name: /搜索 \/ 筛选/ }));

    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      const onlineUrl = urls.find((url) => url.includes("/api/discovery/search?"));
      const localUrl = urls.find((url) => url.startsWith("/api/movies?"));
      expect(onlineUrl).toContain("q=%E6%98%9F%E9%99%85%E7%A9%BF%E8%B6%8A");
      const params = new URLSearchParams(localUrl!.split("?")[1]);
      expect(params.get("type")).toBe("movie");
      expect(params.get("min_year")).toBe("2010");
      expect(params.get("max_year")).toBe("2020");
      expect(params.get("genres")).toBe("科幻");
      expect(params.get("regions")).toBe("美国");
    });
  });

  it("applies the selected rating sort to TMDB discovery", async () => {
    const fetchMock = installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url.startsWith("/api/discovery/regions")) return { provider: "tmdb", regions: [] };
      if (url.startsWith("/api/discovery/discover?")) return {
        provider: "tmdb", media_type: "movie", page: 1, total_pages: 1,
        total_results: 0, items: [], attribution: "TMDB"
      };
      if (url.startsWith("/api/movies?")) return { items: [], next_cursor: null, total: 0 };
      throw new Error(`Unexpected request: ${url}`);
    });
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/search"]}>
        <App />
      </MemoryRouter>
    );
    await userEvent.selectOptions(await screen.findByLabelText("排序方式"), "rating_desc");
    await userEvent.click(screen.getByRole("button", { name: /搜索 \/ 筛选/ }));
    await waitFor(() => {
      const discoverUrl = fetchMock.mock.calls.map(([input]) => String(input))
        .find((url) => url.startsWith("/api/discovery/discover?"));
      expect(discoverUrl).toContain("sort_by=vote_average.desc");
    });
  });

  it("sorts keyword search results by rating and keeps missing ratings last", async () => {
    installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url.startsWith("/api/discovery/regions")) return { provider: "tmdb", regions: [] };
      if (url.startsWith("/api/discovery/search?")) return {
        provider: "tmdb", query: "测试", page: 1, total_pages: 1, total_results: 3,
        items: [
          { provider: "tmdb", provider_id: 1, media_type: "movie", title: "低分", original_title: null, year: 2020, rating: 6.1, rating_count: 500, poster_path: null, backdrop_path: null, genre_ids: [] },
          { provider: "tmdb", provider_id: 2, media_type: "movie", title: "无评分", original_title: null, year: 2021, rating: null, rating_count: 0, poster_path: null, backdrop_path: null, genre_ids: [] },
          { provider: "tmdb", provider_id: 3, media_type: "movie", title: "高分", original_title: null, year: 2022, rating: 8.8, rating_count: 900, poster_path: null, backdrop_path: null, genre_ids: [] }
        ], attribution: "TMDB"
      };
      throw new Error(`Unexpected request: ${url}`);
    });
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/search?search=测试&sort=rating_desc"]}>
        <App />
      </MemoryRouter>
    );
    const cards = await screen.findAllByRole("link", { name: /高分|低分|无评分/ });
    expect(cards.map((node) => node.textContent)).toEqual(["高分", "低分", "无评分"]);
  });

  it("restores URL-selected genre, region, type and year filters before async options load", async () => {
    const fetchMock = installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url === "/api/discovery/regions") {
        return { provider: "tmdb", regions: [{ code: "JP", name: "日本" }] };
      }
      if (url.includes("/api/discovery/genres")) {
        return { provider: "tmdb", media_type: "tv", genres: [{ id: 16, name: "动画" }] };
      }
      if (url.startsWith("/api/discovery/discover?")) {
        return {
          provider: "tmdb", media_type: "tv", page: 1, total_pages: 1,
          total_results: 0, items: [], attribution: "TMDB"
        };
      }
      if (url.startsWith("/api/movies?")) {
        return { items: [], next_cursor: null, total: 0 };
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        initialEntries={["/search?type=tv&genre_ids=16&region_codes=JP&min_year=2010&max_year=2020"]}
      >
        <App />
      </MemoryRouter>
    );

    await screen.findByText("在线搜索结果");
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      const localUrl = urls.find((url) => url.startsWith("/api/movies?"));
      const onlineUrl = urls.find((url) => url.startsWith("/api/discovery/discover?"));
      expect(localUrl).toBeTruthy();
      const local = new URLSearchParams(localUrl!.split("?")[1]);
      expect(local.get("type")).toBe("tv");
      expect(local.get("min_year")).toBe("2010");
      expect(local.get("max_year")).toBe("2020");
      expect(local.get("genres")).toBe("动画");
      expect(local.get("regions")).toBe("日本");
      expect(onlineUrl).toContain("media_type=tv");
      expect(onlineUrl).toContain("with_genres=16");
      expect(onlineUrl).toContain("region=JP");
    });
  });

  it("deduplicates a local Douban result after a verified transient TMDB identity match", async () => {
    installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url.startsWith("/api/discovery/regions")) return { provider: "tmdb", regions: [] };
      if (url.startsWith("/api/discovery/search?")) {
        return {
          provider: "tmdb", query: "肖申克的救赎", page: 1, total_pages: 1,
          total_results: 1,
          items: [{
            provider: "tmdb", provider_id: 278, media_type: "movie",
            title: "肖申克的救赎", original_title: "The Shawshank Redemption", year: 1994,
            rating: 8.7, rating_count: 30000, poster_path: null,
            backdrop_path: null, genre_ids: [], imdb_id: null
          }],
          attribution: "TMDB"
        };
      }
      if (url.startsWith("/api/movies?")) {
        return {
          total: 1, next_cursor: null,
          items: [{
            id: 1, douban_id: "1292052", tmdb_id: null, imdb_id: null,
            title: "肖申克的救赎", original_title: "The Shawshank Redemption", year: 1994,
            rating: 9.7, rating_count: 3367654, type: "movie", genres: [], regions: [], updated_at: null
          }]
        };
      }
      if (url === "/api/movies/id/1") {
        return {
          id: 1, douban_id: "1292052", tmdb_id: null, imdb_id: null,
          title: "肖申克的救赎", original_title: "The Shawshank Redemption", year: 1994,
          rating: 9.7, rating_count: 3367654, type: "movie", genres: [], regions: [],
          directors: ["Frank Darabont"], actors: [], overview: null, douban_url: null, posters: [],
          tmdb_metadata: { provider_id: 278, overview: null, year: 1994, rating: 8.7, rating_count: 30000, genres: [], regions: [], directors: [], actors: [], runtime: 142, poster_path: null }
        };
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/search?search=肖申克的救赎"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("肖申克的救赎")).toHaveLength(1);
      expect(screen.getByText(/本地榜单收录 · 豆瓣 9.7/)).toBeInTheDocument();
    });
  });

  it("deduplicates search results only by stable IDs, not title and year", async () => {
    installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url.startsWith("/api/discovery/search?")) {
        return {
          provider: "tmdb", query: "同名电影", page: 1, total_pages: 1,
          total_results: 1,
          items: [{
            provider: "tmdb", provider_id: 900, media_type: "movie",
            title: "同名电影", original_title: "Same Title", year: 2020,
            rating: 7.5, rating_count: 1200, poster_path: null,
            backdrop_path: null, genre_ids: [], imdb_id: null
          }],
          attribution: "TMDB"
        };
      }
      if (url.startsWith("/api/movies?")) {
        return {
          total: 2, next_cursor: null,
          items: [
            {
              id: 1, douban_id: "10001", tmdb_id: "900", imdb_id: null,
              title: "同名电影", original_title: "Same Title", year: 2020,
              rating: 8.1, rating_count: 300, type: "movie", genres: [], regions: [], updated_at: null
            },
            {
              id: 2, douban_id: "10002", tmdb_id: "901", imdb_id: null,
              title: "同名电影", original_title: "Same Title", year: 2020,
              rating: 7.9, rating_count: 200, type: "movie", genres: [], regions: [], updated_at: null
            }
          ]
        };
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/search?search=同名电影"]}>
        <App />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("同名电影")).toHaveLength(2);
      expect(screen.getAllByText(/本地榜单收录/)).toHaveLength(2);
    });
  });

  it("opens Xiaoya search in a new tab with the movie title URL-encoded", async () => {
    installFetchMock((url) => {
      if (url === "/api/config") {
        return { xiaoyaSearchUrlTemplate: "https://xiaoya.example/search?box={query}&type=video&url=" };
      }
      if (url === "/api/movies/id/42") {
        return {
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
      }
      if (url === "/api/favorites") return [];
      throw new Error(`Unexpected request: ${url}`);
    });
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/movies/42"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByRole("heading", { name: "星际穿越" });
    await userEvent.click(screen.getByRole("button", { name: /在小雅中搜索/ }));

    expect(openSpy).toHaveBeenCalledTimes(1);
    const openedUrl = new URL(openSpy.mock.calls[0][0] as string);
    expect(openedUrl.origin).toBe("https://xiaoya.example");
    expect(openedUrl.pathname).toBe("/search");
    expect(openedUrl.searchParams.get("box")).toBe("星际穿越");
    expect(openSpy.mock.calls[0][1]).toBe("_blank");
  });

  it("compares historical chart snapshots and renders rank movement", async () => {
    const fetchMock = installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url === "/api/charts/top250/snapshots") {
        return [
          { snapshot_date: "2026-11-23", item_count: 2 },
          { snapshot_date: "2026-11-22", item_count: 2 }
        ];
      }
      if (url === "/api/charts/top250") {
        return { chart, items: [], next_cursor: null, total: 0 };
      }
      if (url.startsWith("/api/charts/top250/compare?")) {
        return {
          chart,
          from_date: "2026-11-22",
          to_date: "2026-11-23",
          total_before: 2,
          total_after: 2,
          items: [
            {
              movie_id: 11,
              douban_id: "1001",
              title: "A Movie",
              year: 2020,
              type: "movie",
              before_rank: 2,
              after_rank: 1,
              rank_change: 1,
              status: "moved"
            },
            {
              movie_id: 12,
              douban_id: "1002",
              title: "New Movie",
              year: 2024,
              type: "movie",
              before_rank: null,
              after_rank: 2,
              rank_change: null,
              status: "new"
            }
          ]
        };
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/charts/top250"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByRole("heading", { name: "豆瓣电影 Top 250" });
    await userEvent.click(screen.getByRole("button", { name: "比较排名" }));

    expect(await screen.findByText("A Movie")).toBeInTheDocument();
    expect(screen.getByText("排名变动 · ↑1")).toBeInTheDocument();
    expect(screen.getByText("新上榜")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) =>
      String(input).includes("from_date=2026-11-22")
    )).toBe(true);
  });



  it("clears a previous chart error when navigating to another chart", async () => {
    installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url === "/api/charts/broken/snapshots") return [];
      if (url === "/api/charts/broken") throw new Error("榜单读取失败");
      if (url === "/api/charts/top250/snapshots") return [];
      if (url === "/api/charts/top250") {
        return { chart, items: [], next_cursor: null, total: 0 };
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/charts/broken"]}>
        <Link to="/charts/top250">切换榜单</Link>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByText("榜单读取失败")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "切换榜单" }));

    expect(await screen.findByRole("heading", { name: "豆瓣电影 Top 250" })).toBeInTheDocument();
    expect(screen.queryByText("榜单读取失败")).not.toBeInTheDocument();
    expect(screen.getByText("这份榜单还没有快照")).toBeInTheDocument();
  });

  it("adds and removes a favorite through the protected favorites API", async () => {
    const requests: { url: string; method: string }[] = [];
    installFetchMock((url, init) => {
      const method = init?.method ?? "GET";
      requests.push({ url, method });
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url === "/api/movies/id/42") {
        return {
          id: 42,
          douban_id: "1292052",
          title: "Favorites Fixture",
          original_title: null,
          year: 2024,
          rating: 8.0,
          rating_count: 100,
          type: "movie",
          genres: [],
          regions: [],
          updated_at: null,
          imdb_id: null,
          tmdb_id: null,
          directors: [],
          actors: [],
          overview: null,
          douban_url: null,
          posters: []
        };
      }
      if (url === "/api/favorites" && method === "GET") return [];
      if (url === "/api/favorites/42" && method === "PUT") {
        return {
          movie: {
            id: 42,
            douban_id: "1292052",
            title: "Favorites Fixture",
            original_title: null,
            year: 2024,
            rating: 8.0,
            rating_count: 100,
            type: "movie",
            genres: [],
            regions: [],
            updated_at: null
          },
          created_at: "2026-11-23T00:00:00",
          note: ""
        };
      }
      if (url === "/api/favorites/42" && method === "DELETE") return undefined;
      throw new Error(`Unexpected request: ${method} ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/movies/42"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByRole("heading", { name: "Favorites Fixture" });
    await userEvent.click(screen.getByRole("button", { name: "♡ 加入收藏" }));
    expect(await screen.findByRole("button", { name: "♥ 已收藏" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "♥ 已收藏" }));
    expect(await screen.findByRole("button", { name: "♡ 加入收藏" })).toBeInTheDocument();
    expect(requests).toContainEqual({ url: "/api/favorites/42", method: "PUT" });
    expect(requests).toContainEqual({ url: "/api/favorites/42", method: "DELETE" });
  });

  it("connects the protected favorites APIs with a tab-session API key", async () => {
    const fetchMock = installFetchMock((url, init) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url === "/api/favorites" || url === "/api/favorites/external") {
        const headers = new Headers(init?.headers);
        if (headers.get("X-API-Key") !== "local-test-key") {
          throw new Error("Invalid or missing API key");
        }
        return [];
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/favorites"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByRole("heading", { name: "连接收藏功能" });
    await userEvent.type(
      screen.getByPlaceholderText("输入 NAS 上配置的 MovieHub API Key"),
      "local-test-key"
    );
    await userEvent.click(screen.getByRole("button", { name: "连接收藏" }));

    expect(await screen.findByText("收藏夹还是空的")).toBeInTheDocument();
    expect(window.localStorage.getItem("moviehubApiKey")).toBe("local-test-key");
    expect(fetchMock.mock.calls.some(([, init]) =>
      new Headers(init?.headers).get("X-API-Key") === "local-test-key"
    )).toBe(true);
  });



  it("shows TMDB fallback metadata on a local Douban chart detail without mixing ratings", async () => {
    installFetchMock((url) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "http://zwnas.notedream.com:5678/search?box={query}&type=video&url=" };
      if (url === "/api/movies/id/42") return {
        id: 42, douban_id: "12345", tmdb_id: "900", imdb_id: "tt1234567",
        title: "年度影片", original_title: "Annual Film", year: null,
        rating: 8.4, rating_count: null, type: "movie", genres: [], regions: [],
        updated_at: null, directors: ["豆瓣导演"], actors: [], overview: null,
        douban_url: null, posters: [],
        tmdb_metadata: {
          overview: "来自 TMDB 的临时简介", year: 2025, rating: 7.9,
          rating_count: 2500, genres: ["动画"], regions: ["中国大陆"],
          directors: ["TMDB Director"], actors: ["TMDB Actor"],
          runtime: 110, poster_path: "/annual.jpg"
        }
      };
      if (url.startsWith("/api/favorites/external/status/movie/900")) return { is_favorite: false };
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/movies/42"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByRole("heading", { name: "年度影片" });
    expect(screen.getByText(/FEATURE FILM · 2025/)).toBeInTheDocument();
    expect(screen.getByText("豆瓣 · 暂无评价人数")).toBeInTheDocument();
    expect(screen.getByText(/TMDB · ★ 7.9 · 2,500 票/)).toBeInTheDocument();
    expect(screen.getByText("来自 TMDB 的临时简介")).toBeInTheDocument();
    expect(screen.getByText("豆瓣导演")).toBeInTheDocument();
    expect(screen.getByText("TMDB Actor")).toBeInTheDocument();
  });

  it("recognizes a chart favorite when opening the corresponding TMDB detail", async () => {
    window.localStorage.setItem("moviehubApiKey", "cross-tab-key");
    const fetchMock = installFetchMock((url, init) => {
      if (url === "/api/config") return { xiaoyaSearchUrlTemplate: "" };
      if (url === "/api/discovery/movie/900") return {
        provider: "tmdb", media_type: "movie", provider_id: 900,
        title: "Linked Film", original_title: "Linked Film", year: 2024,
        rating: 7.8, rating_count: 3000, poster_path: null,
        backdrop_path: null, genre_ids: [], overview: null, genres: [],
        production_countries: [], runtime: null, number_of_seasons: null,
        number_of_episodes: null, credits: {}, external_ids: { imdb_id: "tt1234567" },
        attribution: "TMDB"
      };
      if (url.startsWith("/api/favorites/external/status/movie/900")) {
        const headers = new Headers(init?.headers);
        expect(headers.get("X-API-Key")).toBe("cross-tab-key");
        return { is_favorite: true };
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }} initialEntries={["/tmdb/movie/900"]}>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByRole("button", { name: "♥ 已收藏" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });

});
