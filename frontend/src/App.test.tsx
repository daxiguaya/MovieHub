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
  window.sessionStorage.removeItem("moviehubApiKey");
});

describe("MovieHub frontend workflows", () => {
  it("loads chart collections and navigates to a dated chart page", async () => {
    const fetchMock = installFetchMock((url) => {
      if (url === "/config.json") return { xiaoyaSearchBaseUrl: "" };
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
      if (url === "/config.json") return { xiaoyaSearchBaseUrl: "" };
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

  it("opens Xiaoya search in a new tab with the movie title URL-encoded", async () => {
    installFetchMock((url) => {
      if (url === "/config.json") {
        return { xiaoyaSearchBaseUrl: "https://xiaoya.example/search" };
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
      if (url === "/config.json") return { xiaoyaSearchBaseUrl: "" };
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
      if (url === "/config.json") return { xiaoyaSearchBaseUrl: "" };
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
      if (url === "/config.json") return { xiaoyaSearchBaseUrl: "" };
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
      if (url === "/config.json") return { xiaoyaSearchBaseUrl: "" };
      if (url === "/api/favorites" || url === "/api/discovery/favorites") {
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
    expect(window.sessionStorage.getItem("moviehubApiKey")).toBe("local-test-key");
    expect(fetchMock.mock.calls.some(([, init]) =>
      new Headers(init?.headers).get("X-API-Key") === "local-test-key"
    )).toBe(true);
  });


});
