import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useParams,
  useSearchParams
} from "react-router-dom";
import { api } from "./api";
import { loadPublicConfig, openXiaoyaSearch } from "./config";
import { appPath } from "./paths";
import type {
  Chart,
  ChartCompareResponse,
  DiscoveryDetail,
  DiscoveryItem,
  ExternalFavorite,
  ChartMovie,
  Favorite,
  Movie,
  MovieDetail,
  PublicConfig
} from "./types";

function App() {
  const [publicConfig, setPublicConfig] = useState<PublicConfig>({
    xiaoyaSearchBaseUrl: ""
  });

  useEffect(() => {
    void loadPublicConfig().then(setPublicConfig);
  }, []);

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="brand-mark">M</span>
          <span>Movie<span className="brand-light">Hub</span></span>
        </Link>
        <nav className="main-nav" aria-label="主导航">
          <NavLink to="/" end>发现</NavLink>
          <NavLink to="/search">全网搜索</NavLink>
          <NavLink to="/favorites">我的收藏</NavLink>
        </nav>
        <Link className="top-search" to="/search" aria-label="搜索电影">
          <span>⌕</span><span className="top-search-label">搜索电影</span>
        </Link>
      </header>

      <main className="page-container">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/charts/:slug" element={<ChartPage />} />
          <Route path="/discover/:slug" element={<DiscoveryListPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/movies/:movieId" element={<MoviePage config={publicConfig} />} />
          <Route path="/tmdb/:mediaType/:providerId" element={<ExternalMoviePage config={publicConfig} />} />
          <Route path="/favorites" element={<FavoritesPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="site-footer">
        <span>MovieHub</span>
        <span>发现好电影，剩下的交给小雅与 Jellyfin。</span>
      </footer>
    </div>
  );
}

function PageHeading({
  eyebrow,
  title,
  description,
  action
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}

function Loading({ label = "正在加载…" }: { label?: string }) {
  return <div className="state-panel"><span className="spinner" />{label}</div>;
}

function ErrorState({ message }: { message: string }) {
  return <div className="state-panel error-state"><strong>暂时无法加载</strong><span>{message}</span></div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><span className="empty-icon">✳</span><strong>{title}</strong><p>{detail}</p></div>;
}

function HomePage() {
  const [charts, setCharts] = useState<Chart[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.charts()
      .then((data) => { if (active) setCharts(data); })
      .catch((err: Error) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const groups = useMemo(() => [
    { title: "经典必看", description: "经得起时间考验的电影", items: charts.filter((c) => c.category === "classic") },
    { title: "正在热门", description: "看看最近大家在看什么", items: charts.filter((c) => c.category === "popular") },
    { title: "高分精选", description: "从口碑出发，发现好作品", items: charts.filter((c) => c.category === "rating") },
    { title: "年度榜单", description: "按年份回顾值得关注的作品", items: charts.filter((c) => c.category === "annual") }
  ], [charts]);

  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow"><span className="live-dot" /> YOUR PERSONAL MOVIE DISCOVERY</div>
          <h1>好电影，<br /><em>值得被发现。</em></h1>
          <p>从经典榜单到年度精选，找到下一部想看的电影。<br />发现之后，一键交给小雅搜索。</p>
          <Link className="primary-button" to="/search">开始探索 <span>↗</span></Link>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="poster-stack stack-back"><div className="poster-art-art" /></div>
          <div className="poster-stack stack-mid"><div className="poster-art-moon" /></div>
          <div className="poster-stack stack-front">
            <div className="poster-art-sun" />
            <div className="poster-art-title">THE<br />NEXT<br /><b>STORY</b></div>
            <div className="poster-art-caption">A FILM TO REMEMBER</div>
          </div>
          <div className="hero-stamp">CURATED<br />FOR YOU</div>
        </div>
      </section>

      <div className="section-heading">
        <div><div className="eyebrow">EXPLORE COLLECTIONS</div><h2>从一份好榜单开始</h2></div>
        <Link className="text-link" to="/search">浏览全部电影 <span>→</span></Link>
      </div>

      <DiscoverySpotlight />

      {loading ? <Loading label="正在读取榜单…" /> : error ? <ErrorState message={error} /> : (
        groups.map((group) => group.items.length > 0 && (
          <section className="chart-group" key={group.title}>
            <div className="group-heading">
              <div><h3>{group.title}</h3><p>{group.description}</p></div>
            </div>
            <div className="chart-grid">
              {group.items.map((chart) => <ChartTile key={chart.slug} chart={chart} />)}
            </div>
          </section>
        ))
      )}
      {!loading && !error && charts.length === 0 && (
        <EmptyState title="榜单还没有数据" detail="先导入一份榜单快照，MovieHub 就会在这里展示它。" />
      )}
      <section className="discovery-note">
        <div className="note-icon">↗</div>
        <div><strong>发现电影，然后交给小雅</strong><p>MovieHub 专注发现与整理。搜索资源、下载和播放仍由你现有的小雅与 Jellyfin 负责。</p></div>
      </section>
    </>
  );
}

const DISCOVERY_LISTS: Record<string, {
  title: string;
  description: string;
  genre: string;
  minVotes: number;
  maxVotes?: number;
  minRating: number;
}> = {
  "horror-high": {
    title: "恐怖片高分榜",
    description: "投票量充足、口碑稳定的恐怖电影",
    genre: "27",
    minVotes: 500,
    minRating: 7
  },
  "horror-gems": {
    title: "恐怖片冷门佳作",
    description: "投票量适中、评分优秀的恐怖片遗珠",
    genre: "27",
    minVotes: 50,
    maxVotes: 5000,
    minRating: 6.5
  },
  "thriller-high": {
    title: "惊悚片高分榜",
    description: "投票量充足、口碑稳定的惊悚电影",
    genre: "53",
    minVotes: 500,
    minRating: 7
  },
  "thriller-gems": {
    title: "惊悚片冷门佳作",
    description: "投票量适中、评分优秀的惊悚片遗珠",
    genre: "53",
    minVotes: 50,
    maxVotes: 5000,
    minRating: 6.5
  }
};

function DiscoveryListPage() {
  const { slug = "" } = useParams();
  const definition = DISCOVERY_LISTS[slug];
  const [items, setItems] = useState<DiscoveryItem[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(nextPage: number, append = false) {
    if (!definition) return;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      media_type: "movie",
      page: String(nextPage),
      with_genres: definition.genre,
      min_votes: String(definition.minVotes),
      min_rating: String(definition.minRating),
      sort_by: "vote_average.desc"
    });
    if (definition.maxVotes) params.set("max_votes", String(definition.maxVotes));
    try {
      const data = await api.discoveryDiscover(params);
      setItems((current) => append ? current.concat(data.items) : data.items);
      setPage(data.page);
      setTotalPages(data.total_pages);
      setTotal(data.total_results);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setItems([]);
    setPage(1);
    setTotalPages(0);
    setTotal(0);
    if (definition) void load(1);
    else setLoading(false);
    // The selected definition is derived from the route slug.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  if (!definition) return <ErrorState message="没有找到这份专题榜单" />;

  return (
    <>
      <div className="breadcrumb"><Link to="/">发现</Link><span>/</span><span>恐怖与惊悚专题</span></div>
      <PageHeading eyebrow="HORROR & THRILLER" title={definition.title} description={definition.description + "。按页在线获取，不做全量导入。"} />
      <div className="result-caption"><span>TMDB 在线精选</span><span>{total.toLocaleString()} 部 · 第 {page} / {Math.max(totalPages, 1)} 页</span></div>
      {error && <div className="inline-error">{error}</div>}
      {items.length > 0 ? (
        <>
          <div className="movie-grid">{items.map((item) => <ExternalMovieCard key={item.media_type + ":" + item.provider_id} item={item} />)}</div>
          {page < totalPages && <button className="secondary-button load-more" onClick={() => void load(page + 1, true)} disabled={loading}>{loading ? "正在加载…" : "加载下一页"}</button>}
        </>
      ) : loading ? <Loading /> : <EmptyState title="暂时没有符合条件的作品" detail="可以稍后再试，或降低投票数门槛。" />}
      <p className="tmdb-attribution">This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
    </>
  );
}

function DiscoverySpotlight() {
  const [lists, setLists] = useState<{ key: string; title: string; items: DiscoveryItem[] }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const definitions = [
      { key: "horror-high", title: "恐怖片高分榜", genre: "27", votes: "500", sort: "vote_average.desc" },
      { key: "horror-gems", title: "恐怖片冷门佳作", genre: "27", votes: "50", sort: "vote_average.desc" },
      { key: "thriller-high", title: "惊悚片高分榜", genre: "53", votes: "500", sort: "vote_average.desc" },
      { key: "thriller-gems", title: "惊悚片冷门佳作", genre: "53", votes: "50", sort: "vote_average.desc" }
    ];
    Promise.all(definitions.map(async (definition) => {
      const params = new URLSearchParams({
        media_type: "movie",
        page: "1",
        with_genres: definition.genre,
        min_votes: definition.votes,
        min_rating: definition.votes === "50" ? "6.5" : "7",
        sort_by: definition.sort
      });
      const data = await api.discoveryDiscover(params);
      return { key: definition.key, title: definition.title, items: data.items.slice(0, 5) };
    })).then((data) => { if (active) setLists(data); })
      .catch(() => { if (active) setLists([]); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  return (
    <section className="genre-spotlight">
      <div className="section-heading">
        <div><div className="eyebrow">HORROR & THRILLER</div><h2>恐怖与惊悚专题</h2><p>专门为类型片爱好者精选，按口碑和投票量动态发现作品。</p></div>
        <Link className="text-link" to="/search">更多类型筛选 <span>→</span></Link>
      </div>
      {loading ? <Loading label="正在加载恐怖与惊悚精选…" /> : lists.length === 0 ? (
        <div className="spotlight-fallback">专题数据暂时不可用，可进入全网搜索继续查找。</div>
      ) : (
        <div className="spotlight-grid">
          {lists.map((list) => (
            <section className="spotlight-panel" key={list.key}>
              <h3>{list.title}</h3>
              {list.items.map((item) => (
                <Link className="spotlight-item" key={item.media_type + ":" + item.provider_id} to={"/tmdb/" + item.media_type + "/" + item.provider_id}>
                  {item.poster_path ? <img src={"https://image.tmdb.org/t/p/w92" + item.poster_path} alt="" loading="lazy" /> : <span className="spotlight-placeholder">MH</span>}
                  <span className="spotlight-item-copy"><strong>{item.title}</strong><small>{item.year ?? "年份未知"} · ★ {item.rating?.toFixed(1) ?? "—"} · {item.rating_count.toLocaleString()} 票</small></span>
                </Link>
              ))}
              {list.items.length === 0 && <p className="spotlight-empty">暂无符合条件的作品</p>}
            </section>
          ))}
        </div>
      )}
      <p className="tmdb-attribution">This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
    </section>
  );
}

function ChartTile({ chart }: { chart: Chart }) {
  const descriptions: Record<string, string> = {
    top250: "影史经典，历久弥新",
    popular: "此刻正在被讨论",
    "high-rated": "口碑与评分兼顾",
    "annual-2025-chinese-movies": "年度华语电影口碑榜",
    "annual-2025-international-movies": "年度外语电影精选",
    "annual-2025-hidden-gems": "值得发现的年度佳片",
    "annual-2025-chinese-tv": "年度华语剧集口碑榜"
  };
  return (
    <Link className="chart-tile" to={`/charts/${chart.slug}`}>
      <div className={`chart-tile-art art-${chart.category}`}>
        <span className="tile-number">{String(chart.display_order / 10).padStart(2, "0")}</span>
        <span className="tile-art-label">{chart.period ?? chart.source.toUpperCase()}</span>
        <span className="tile-art-title">{chart.name}</span>
        <span className="tile-arrow">↗</span>
      </div>
      <div className="tile-meta"><strong>{chart.name}</strong><span>{descriptions[chart.slug] ?? chart.description ?? "精选电影榜单"}</span></div>
    </Link>
  );
}

function MoviePoster({ movie, rank }: { movie: Movie; rank?: number }) {
  const [failed, setFailed] = useState(false);
  return (
    <Link className="movie-poster" to={`/movies/${movie.id}`}>
      {movie.douban_id && <span className="poster-badge">{rank ? `#${rank}` : movie.type === "tv" ? "剧集" : "电影"}</span>}
      {!failed ? (
        <img
          src={appPath(`api/movies/${movie.id}/poster`)}
          alt={movie.title}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="poster-placeholder"><span>MH</span><small>{movie.year ?? "MOVIE"}</small></div>
      )}
    </Link>
  );
}

function MovieCard({ movie, rank }: { movie: Movie; rank?: number }) {
  return (
    <article className="movie-card">
      <MoviePoster movie={movie} rank={rank} />
      <div className="movie-card-info">
        <Link to={`/movies/${movie.id}`} className="movie-title">{movie.title}</Link>
        <div className="movie-subtitle">{movie.year ?? "年份未知"} · {movie.type === "tv" ? "剧集" : "电影"}</div>
        <div className="movie-rating"><span>★</span> {movie.rating?.toFixed(1) ?? "暂无评分"} <small>({movie.rating_count.toLocaleString()})</small></div>
      </div>
    </article>
  );
}


function ExternalMovieCard({ item }: { item: DiscoveryItem }) {
  const [failed, setFailed] = useState(false);
  const poster = item.poster_path ? "https://image.tmdb.org/t/p/w342" + item.poster_path : "";
  return (
    <article className="movie-card">
      <Link className="movie-poster" to={"/tmdb/" + item.media_type + "/" + item.provider_id}>
        <span className="poster-badge">{item.media_type === "tv" ? "剧集" : "电影"}</span>
        {!failed && poster ? (
          <img src={poster} alt={item.title} loading="lazy" onError={() => setFailed(true)} />
        ) : (
          <div className="poster-placeholder"><span>TMDB</span><small>{item.year ?? "TITLE"}</small></div>
        )}
      </Link>
      <div className="movie-card-info">
        <Link to={"/tmdb/" + item.media_type + "/" + item.provider_id} className="movie-title">{item.title}</Link>
        <div className="movie-subtitle">{item.year ?? "年份未知"} · {item.media_type === "tv" ? "剧集" : "电影"}</div>
        <div className="movie-rating"><span>★</span> TMDB {item.rating?.toFixed(1) ?? "暂无评分"} <small>({item.rating_count.toLocaleString()})</small></div>
      </div>
    </article>
  );
}

function ChartPage() {
  const { slug = "" } = useParams();
  const [snapshots, setSnapshots] = useState<{ snapshot_date: string; item_count: number }[]>([]);
  const [snapshotDate, setSnapshotDate] = useState("");
  const [items, setItems] = useState<ChartMovie[]>([]);
  const [chartName, setChartName] = useState("");
  const [total, setTotal] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [compareFrom, setCompareFrom] = useState("");
  const [compareTo, setCompareTo] = useState("");
  const [comparison, setComparison] = useState<ChartCompareResponse | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setItems([]);
    setSnapshots([]);
    setSnapshotDate("");
    setChartName("");
    setTotal(0);
    setNextCursor(null);
    setCompareFrom("");
    setCompareTo("");
    setComparison(null);
    setCompareError("");
    setCompareLoading(false);
    Promise.all([api.snapshots(slug), api.chart(slug)])
      .then(([history, latest]) => {
        if (!active) return;
        setSnapshots(history);
        setSnapshotDate(history[0]?.snapshot_date ?? "");
        setCompareTo(history[0]?.snapshot_date ?? "");
        setCompareFrom(history[1]?.snapshot_date ?? "");
        setChartName(latest.chart.name);
        setItems(latest.items);
        setTotal(latest.total);
        setNextCursor(latest.next_cursor);
      })
      .catch((err: Error) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [slug]);

  async function changeSnapshot(day: string) {
    setSnapshotDate(day);
    setLoading(true);
    setError("");
    try {
      const data = await api.chart(slug, day || undefined);
      setItems(data.items);
      setTotal(data.total);
      setNextCursor(data.next_cursor);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function loadMore() {
    if (!nextCursor) return;
    try {
      const data = await api.chart(slug, snapshotDate || undefined, nextCursor);
      setItems((current) => [...current, ...data.items]);
      setNextCursor(data.next_cursor);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function runComparison() {
    if (!compareFrom || !compareTo || compareFrom === compareTo) return;
    setCompareLoading(true);
    setCompareError("");
    try {
      setComparison(await api.compareChart(slug, compareFrom, compareTo));
    } catch (err) {
      setCompareError((err as Error).message);
      setComparison(null);
    } finally {
      setCompareLoading(false);
    }
  }

  const statusLabel: Record<string, string> = {
    new: "新上榜",
    removed: "已退出",
    moved: "排名变动",
    unchanged: "排名不变"
  };

  return (
    <>
      <div className="breadcrumb"><Link to="/">发现</Link><span>/</span><span>榜单</span></div>
      <PageHeading
        eyebrow="CHART COLLECTION"
        title={chartName || "榜单详情"}
        description="按日期查看榜单快照，回顾每一次排名变化。"
        action={snapshots.length > 0 ? (
          <label className="select-wrap">历史日期
            <select value={snapshotDate} onChange={(e) => void changeSnapshot(e.target.value)}>
              {snapshots.map((item) => <option key={item.snapshot_date} value={item.snapshot_date}>{item.snapshot_date} · {item.item_count} 部</option>)}
            </select>
          </label>
        ) : undefined}
      />
      {loading ? <Loading /> : error ? <ErrorState message={error} /> : items.length === 0 ? (
        <EmptyState title="这份榜单还没有快照" detail="导入标准化 JSON 快照后，就能在这里查看榜单内容与历史日期。" />
      ) : (
        <>
          <div className="result-caption"><span>{snapshotDate || "最新快照"}</span><span>{total} 部作品</span></div>
          <div className="movie-grid">{items.map((movie) => <MovieCard key={movie.id} movie={movie} rank={movie.rank} />)}</div>
          {nextCursor && <button className="secondary-button load-more" onClick={() => void loadMore()}>加载更多</button>}
        </>
      )}
      {snapshots.length >= 2 && (
        <section className="rank-compare">
          <div className="rank-compare-heading">
            <div><div className="eyebrow">HISTORY TRACKER</div><h2>榜单排名变化</h2><p>比较两个日期，查看上升、下降、新上榜与退出榜单的作品。</p></div>
          </div>
          <div className="compare-controls">
            <label>对比起始日期<select value={compareFrom} onChange={(e) => setCompareFrom(e.target.value)}>{snapshots.map((item) => <option key={item.snapshot_date} value={item.snapshot_date}>{item.snapshot_date}</option>)}</select></label>
            <span className="compare-arrow">→</span>
            <label>对比结束日期<select value={compareTo} onChange={(e) => setCompareTo(e.target.value)}>{snapshots.map((item) => <option key={item.snapshot_date} value={item.snapshot_date}>{item.snapshot_date}</option>)}</select></label>
            <button className="primary-button" disabled={!compareFrom || !compareTo || compareFrom === compareTo || compareLoading} onClick={() => void runComparison()}>{compareLoading ? "正在比较…" : "比较排名"}</button>
          </div>
          {compareError && <div className="inline-error">{compareError}</div>}
          {comparison && (
            <>
              <div className="result-caption"><span>{comparison.from_date} → {comparison.to_date}</span><span>{comparison.total_before} → {comparison.total_after} 部作品</span></div>
              <div className="rank-change-list">
                {comparison.items.map((item) => (
                  <div className="rank-change-row" key={item.movie_id}>
                    <div className="rank-change-title"><strong>{item.title}</strong><span>{item.year ?? "年份未知"}</span></div>
                    <div className="rank-position">{item.before_rank ? `#${item.before_rank}` : "—"} <span>→</span> {item.after_rank ? `#${item.after_rank}` : "—"}</div>
                    <span className={`rank-status status-${item.status}`}>{statusLabel[item.status]}{item.rank_change !== null ? ` · ${item.rank_change > 0 ? `↑${item.rank_change}` : item.rank_change < 0 ? `↓${Math.abs(item.rank_change)}` : "0"}` : ""}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>
      )}
    </>
  );
}

function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [keyword, setKeyword] = useState(searchParams.get("search") ?? "");
  const [type, setType] = useState<"all" | "movie" | "tv">((searchParams.get("type") as "all" | "movie" | "tv" | null) ?? "all");
  const [minRating, setMinRating] = useState(searchParams.get("min_rating") ?? "");
  const [minRatingCount, setMinRatingCount] = useState(searchParams.get("min_rating_count") ?? "100");
  const [minYear, setMinYear] = useState(searchParams.get("min_year") ?? "");
  const [maxYear, setMaxYear] = useState(searchParams.get("max_year") ?? "");
  const [genreOptions, setGenreOptions] = useState<{ id: number; name: string }[]>([]);
  const [regionOptions, setRegionOptions] = useState<{ code: string; name: string }[]>([]);
  const [selectedGenres, setSelectedGenres] = useState<string[]>(searchParams.get("genre_ids")?.split("|") ?? []);
  const [selectedRegions, setSelectedRegions] = useState<string[]>(searchParams.get("region_codes")?.split("|") ?? []);
  const [results, setResults] = useState<Movie[]>([]);
  const [onlineResults, setOnlineResults] = useState<DiscoveryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [onlineTotal, setOnlineTotal] = useState(0);
  const [onlinePage, setOnlinePage] = useState(1);
  const [onlinePages, setOnlinePages] = useState(0);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [onlineError, setOnlineError] = useState("");
  const [hasSearched, setHasSearched] = useState(false);

  useEffect(() => {
    let active = true;
    api.discoveryRegions().then((data) => { if (active) setRegionOptions(data.regions); }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    api.discoveryGenres(type === "tv" ? "tv" : "movie")
      .then((data) => { if (active) setGenreOptions(data.genres); })
      .catch(() => { if (active) setGenreOptions([]); });
    return () => { active = false; };
  }, [type]);

  async function runSearch(params: URLSearchParams, appendLocal = false, appendOnline = false) {
    const q = (params.get("search") ?? "").trim();
    const requestedPage = appendOnline ? onlinePage + 1 : 1;
    const hasFilters = Boolean(
      params.get("genre_ids") || params.get("region_codes") || params.get("min_year") ||
      params.get("max_year") || params.get("min_rating") || params.get("min_rating_count")
    );
    setLoading(true);
    setHasSearched(true);
    setError("");
    setOnlineError("");
    try {
      const localParams = new URLSearchParams();
      if (q) localParams.set("search", q);
      if (type !== "all") localParams.set("type", type);
      if (params.get("min_rating")) localParams.set("min_rating", params.get("min_rating")!);
      if (params.get("min_rating_count")) localParams.set("min_rating_count", params.get("min_rating_count")!);
      if (params.get("min_year")) localParams.set("min_year", params.get("min_year")!);
      if (params.get("max_year")) localParams.set("max_year", params.get("max_year")!);
      const genreNames = selectedGenres.map((id) => genreOptions.find((item) => String(item.id) === id)?.name).filter(Boolean);
      const regionNames = selectedRegions.map((code) => regionOptions.find((item) => item.code === code)?.name).filter(Boolean);
      if (genreNames.length) localParams.set("genres", genreNames.join(","));
      if (regionNames.length) localParams.set("regions", regionNames.join(","));
      const hasLocalCriteria = localParams.toString().length > 0;

      const localPromise = hasLocalCriteria
        ? api.movies(localParams)
        : Promise.resolve({ items: [] as Movie[], total: 0, next_cursor: null as string | null });

      let onlinePromise: Promise<import("./types").DiscoverySearchResponse> | null = null;
      if (q.length >= 2) {
        onlinePromise = api.discoverySearch(q, type === "all" ? "all" : type, requestedPage);
      } else if (hasFilters) {
        const discoverParams = new URLSearchParams({
          media_type: type === "tv" ? "tv" : "movie",
          page: String(requestedPage),
          min_votes: params.get("min_rating_count") || "100",
          sort_by: minRating ? "vote_average.desc" : "popularity.desc"
        });
        if (selectedGenres.length) discoverParams.set("with_genres", selectedGenres.join("|"));
        if (selectedRegions.length) discoverParams.set("region", selectedRegions.join("|"));
        if (minRating) discoverParams.set("min_rating", minRating);
        if (minYear) discoverParams.set("min_year", minYear);
        if (maxYear) discoverParams.set("max_year", maxYear);
        onlinePromise = api.discoveryDiscover(discoverParams);
      }

      const [localResult, onlineResult] = await Promise.allSettled([
        localPromise,
        onlinePromise ?? Promise.resolve(null)
      ]);
      if (localResult.status === "fulfilled") {
        const local = localResult.value;
        setResults((current) => appendLocal ? current.concat(local.items) : local.items);
        setTotal(local.total);
        setNextCursor(local.next_cursor);
      } else {
        setError((localResult.reason as Error).message);
      }
      if (onlineResult.status === "fulfilled" && onlineResult.value) {
        const online = onlineResult.value;
        setOnlineResults((current) => appendOnline ? current.concat(online.items) : online.items);
        setOnlineTotal(online.total_results);
        setOnlinePage(online.page);
        setOnlinePages(online.total_pages);
      } else if (onlineResult.status === "rejected") {
        setOnlineError((onlineResult.reason as Error).message);
        if (!appendOnline) {
          setOnlineResults([]);
          setOnlineTotal(0);
          setOnlinePage(1);
          setOnlinePages(0);
        }
      } else if (!appendOnline) {
        setOnlineResults([]);
        setOnlineTotal(0);
        setOnlinePage(1);
        setOnlinePages(0);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (searchParams.toString()) void runSearch(new URLSearchParams(searchParams));
    // Initial query state is restored from the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submit(event: FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (keyword.trim()) params.set("search", keyword.trim());
    if (type !== "all") params.set("type", type);
    if (minRating) params.set("min_rating", minRating);
    if (minRatingCount) params.set("min_rating_count", minRatingCount);
    if (minYear) params.set("min_year", minYear);
    if (maxYear) params.set("max_year", maxYear);
    if (selectedGenres.length) params.set("genre_ids", selectedGenres.join("|"));
    if (selectedRegions.length) params.set("region_codes", selectedRegions.join("|"));
    setSearchParams(params);
    void runSearch(params);
  }

  function loadMoreLocal() {
    if (!nextCursor) return;
    const params = new URLSearchParams(searchParams);
    params.set("cursor", nextCursor);
    void api.movies(params).then((data) => {
      setResults((current) => current.concat(data.items));
      setNextCursor(data.next_cursor);
    }).catch((err: Error) => setError(err.message));
  }

  function loadMoreOnline() {
    if (onlinePage >= onlinePages || loading) return;
    const nextPage = onlinePage + 1;
    const q = (searchParams.get("search") ?? "").trim();
    const request = q.length >= 2
      ? api.discoverySearch(q, type === "all" ? "all" : type, nextPage)
      : api.discoveryDiscover(new URLSearchParams({
          media_type: type === "tv" ? "tv" : "movie",
          page: String(nextPage),
          min_votes: searchParams.get("min_rating_count") || "100",
          sort_by: minRating ? "vote_average.desc" : "popularity.desc",
          ...(searchParams.get("genre_ids") ? { with_genres: searchParams.get("genre_ids")! } : {}),
          ...(searchParams.get("region_codes") ? { region: searchParams.get("region_codes")! } : {}),
          ...(searchParams.get("min_rating") ? { min_rating: searchParams.get("min_rating")! } : {}),
          ...(searchParams.get("min_year") ? { min_year: searchParams.get("min_year")! } : {}),
          ...(searchParams.get("max_year") ? { max_year: searchParams.get("max_year")! } : {})
        }));
    setLoading(true);
    request.then((data) => {
      setOnlineResults((current) => current.concat(data.items));
      setOnlinePage(data.page);
      setOnlinePages(data.total_pages);
    }).catch((err: Error) => setOnlineError(err.message)).finally(() => setLoading(false));
  }

  const localOnly = results.filter((movie) => !onlineResults.some((item) =>
    (movie.tmdb_id === String(item.provider_id) && movie.type === item.media_type) ||
    (movie.title.trim().toLowerCase() === item.title.trim().toLowerCase() && movie.year === item.year)
  ));

  return (
    <>
      <PageHeading eyebrow="ONLINE DISCOVERY" title="搜索全网电影与剧集" description="在线搜索 TMDB 的电影和剧集目录；搜索结果按页加载，不会把全站资料一次性下载到 NAS。" />
      <form className="search-panel" onSubmit={submit}>
        <label className="search-input"><span>⌕</span><input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="输入片名，例如：异形、蝙蝠侠…" /></label>
        <label>影视类型<select value={type} onChange={(e) => setType(e.target.value as "all" | "movie" | "tv")}><option value="all">电影和剧集</option><option value="movie">电影</option><option value="tv">剧集</option></select></label>
        <label>最低 TMDB 评分<select value={minRating} onChange={(e) => setMinRating(e.target.value)}><option value="">不限</option><option value="5">5.0+</option><option value="6">6.0+</option><option value="7">7.0+</option><option value="8">8.0+</option></select></label>
        <label>最低投票数<input type="number" min="0" max="10000000" value={minRatingCount} onChange={(e) => setMinRatingCount(e.target.value)} placeholder="默认 100" /></label>
        <label>起始年份<input type="number" min="1870" max="2100" value={minYear} onChange={(e) => setMinYear(e.target.value)} placeholder="例如 2000" /></label>
        <label>结束年份<input type="number" min="1870" max="2100" value={maxYear} onChange={(e) => setMaxYear(e.target.value)} placeholder="例如 2026" /></label>
        <label>类型（可多选）<select multiple value={selectedGenres} onChange={(e) => setSelectedGenres(Array.from(e.target.selectedOptions).map((option) => option.value))}>
          {genreOptions.map((genre) => <option key={genre.id} value={String(genre.id)}>{genre.name}</option>)}
        </select></label>
        <label>制作地区（可多选）<select multiple value={selectedRegions} onChange={(e) => setSelectedRegions(Array.from(e.target.selectedOptions).map((option) => option.value))}>
          {regionOptions.map((region) => <option key={region.code} value={region.code}>{region.name}</option>)}
        </select></label>
        <button className="primary-button" type="submit">搜索 / 筛选 <span>→</span></button>
      </form>
      <p className="search-hint">关键词模式搜索全网目录；清空关键词后，类型、地区、年份和评分筛选会使用 TMDB Discover。每次只加载当前页。</p>
      <div className="result-caption"><span>在线搜索结果</span><span>{onlineTotal.toLocaleString()} 部 · 本地匹配 {total.toLocaleString()} 部 · 当前第 {onlinePage || 1} 页</span></div>
      {onlineError && <div className="inline-error">{onlineError}</div>}
      {error && <div className="inline-error">{error}</div>}
      {onlineResults.length > 0 ? (
        <>
          <div className="movie-grid">{onlineResults.map((item) => <ExternalMovieCard key={item.media_type + ":" + item.provider_id} item={item} />)}</div>
          {onlinePage < onlinePages && <button className="secondary-button load-more" onClick={loadMoreOnline} disabled={loading}>{loading ? "正在加载…" : "加载更多在线结果"}</button>}
        </>
      ) : loading ? <Loading /> : hasSearched ? (
        <EmptyState title="没有找到匹配的作品" detail="试试更短的片名，或放宽类型、地区、年份和评分条件。" />
      ) : (
        <EmptyState title="输入片名或选择筛选条件" detail="关键词搜索覆盖在线电影和剧集；不输入关键词时，可以使用类型、地区、年份和评分发现作品。" />
      )}
      {localOnly.length > 0 && (
        <>
          <div className="section-heading"><div><div className="eyebrow">LOCAL CHART MATCHES</div><h2>本地榜单中的匹配作品</h2></div></div>
          <div className="movie-grid">{localOnly.map((movie) => <MovieCard key={movie.id} movie={movie} />)}</div>
          {nextCursor && <button className="secondary-button load-more" onClick={loadMoreLocal}>加载更多本地匹配</button>}
        </>
      )}
      <p className="tmdb-attribution">This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
    </>
  );
}

function MoviePage({ config }: { config: PublicConfig }) {
  const { movieId = "" } = useParams();
  const id = Number(movieId);
  const [movie, setMovie] = useState<MovieDetail | null>(null);
  const [isFavorite, setIsFavorite] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [favoriteError, setFavoriteError] = useState("");

  useEffect(() => {
    let active = true;
    if (!Number.isInteger(id) || id <= 0) {
      setError("电影编号无效");
      setLoading(false);
      return;
    }
    setLoading(true);
    api.movie(id)
      .then((data) => { if (active) setMovie(data); })
      .catch((err: Error) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    api.favorites()
      .then((items) => { if (active) setIsFavorite(items.some((item) => item.movie.id === id)); })
      .catch(() => { /* Favorites are protected separately by the reverse proxy. */ });
    return () => { active = false; };
  }, [id]);

  async function toggleFavorite() {
    if (!movie) return;
    setFavoriteError("");
    try {
      if (isFavorite) await api.removeFavorite(movie.id);
      else await api.addFavorite(movie.id);
      setIsFavorite(!isFavorite);
    } catch (err) {
      setFavoriteError((err as Error).message);
    }
  }

  if (loading) return <Loading label="正在读取电影资料…" />;
  if (error || !movie) return <ErrorState message={error || "电影不存在"} />;

  return (
    <>
      <div className="breadcrumb"><Link to="/">发现</Link><span>/</span><Link to="/search">电影库</Link><span>/</span><span>{movie.title}</span></div>
      <section className="detail-layout">
        <div className="detail-poster-wrap">
          <MoviePoster movie={movie} />
          <div className="detail-poster-caption">MOVIEHUB COLLECTION</div>
        </div>
        <div className="detail-copy">
          <div className="eyebrow">{movie.type === "tv" ? "TELEVISION SERIES" : "FEATURE FILM"} · {movie.year ?? "YEAR UNKNOWN"}</div>
          <h1>{movie.title}</h1>
          {movie.original_title && <div className="original-title">{movie.original_title}</div>}
          <div className="detail-rating"><strong>★ {movie.rating?.toFixed(1) ?? "暂无评分"}</strong><span>{movie.rating_count.toLocaleString()} 人评价</span></div>
          <div className="tag-row">{movie.genres.map((tag) => <span className="tag" key={tag}>{tag}</span>)}{movie.regions.map((tag) => <span className="tag muted-tag" key={tag}>{tag}</span>)}</div>
          <div className="detail-actions">
            <button className="primary-button" onClick={() => openXiaoyaSearch(config.xiaoyaSearchBaseUrl, movie.title)} disabled={!config.xiaoyaSearchBaseUrl}>在小雅中搜索 <span>↗</span></button>
            <button className={`secondary-button ${isFavorite ? "is-saved" : ""}`} onClick={() => void toggleFavorite()}>{isFavorite ? "♥ 已收藏" : "♡ 加入收藏"}</button>
            {movie.douban_url && <a className="secondary-button" href={movie.douban_url} target="_blank" rel="noreferrer">豆瓣资料 ↗</a>}
          </div>
          {favoriteError && <div className="inline-error">{favoriteError}</div>}
          {movie.overview && <section className="detail-section"><h3>剧情简介</h3><p>{movie.overview}</p></section>}
          {movie.directors.length > 0 && <section className="detail-section"><h3>导演</h3><p>{movie.directors.join(" / ")}</p></section>}
          {movie.actors.length > 0 && <section className="detail-section"><h3>主演</h3><p>{movie.actors.join(" / ")}</p></section>}
        </div>
      </section>
    </>
  );
}

function ExternalMoviePage({ config }: { config: PublicConfig }) {
  const { mediaType = "movie", providerId = "" } = useParams();
  const id = Number(providerId);
  const validType = mediaType === "tv" ? "tv" : "movie";
  const [movie, setMovie] = useState<DiscoveryDetail | null>(null);
  const [isFavorite, setIsFavorite] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [favoriteError, setFavoriteError] = useState("");

  useEffect(() => {
    let active = true;
    if (!Number.isInteger(id) || id <= 0 || (mediaType !== "movie" && mediaType !== "tv")) {
      setError("作品编号无效");
      setLoading(false);
      return;
    }
    setLoading(true);
    api.discoveryDetail(validType, id)
      .then((data) => { if (active) setMovie(data); })
      .catch((err: Error) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    api.externalFavorites()
      .then((items) => { if (active) setIsFavorite(items.some((item) => item.media_type === validType && item.provider_id === id)); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [id, mediaType, validType]);

  async function toggleFavorite() {
    if (!movie) return;
    setFavoriteError("");
    try {
      if (isFavorite) await api.removeExternalFavorite(validType, id);
      else await api.saveExternalFavorite(movie);
      setIsFavorite(!isFavorite);
    } catch (err) {
      setFavoriteError((err as Error).message);
    }
  }

  if (loading) return <Loading label="正在获取在线作品详情…" />;
  if (error || !movie) return <ErrorState message={error || "作品不存在"} />;

  const poster = movie.poster_path ? "https://image.tmdb.org/t/p/w500" + movie.poster_path : "";
  const directors = movie.credits.crew?.filter((person) => person.job === "Director").map((person) => person.name) ?? [];
  const actors = movie.credits.cast?.slice(0, 12).map((person) => person.name) ?? [];
  const countries = movie.production_countries.map((country) =>
    typeof country === "string" ? country : (country.name || country.iso_3166_1 || "")
  ).filter(Boolean);

  return (
    <>
      <div className="breadcrumb"><Link to="/">发现</Link><span>/</span><Link to="/search">全网搜索</Link><span>/</span><span>{movie.title}</span></div>
      <section className="detail-layout">
        <div className="detail-poster-wrap">
          <div className="movie-poster">
            {poster ? <img src={poster} alt={movie.title} loading="lazy" /> : <div className="poster-placeholder"><span>TMDB</span><small>{movie.year ?? "TITLE"}</small></div>}
          </div>
          <div className="detail-poster-caption">TMDB DISCOVERY</div>
        </div>
        <div className="detail-copy">
          <div className="eyebrow">{movie.media_type === "tv" ? "TELEVISION SERIES" : "FEATURE FILM"} · {movie.year ?? "YEAR UNKNOWN"}</div>
          <h1>{movie.title}</h1>
          {movie.original_title && <div className="original-title">{movie.original_title}</div>}
          <div className="detail-rating"><strong>★ {movie.rating?.toFixed(1) ?? "暂无评分"}</strong><span>TMDB · {movie.rating_count.toLocaleString()} 票</span></div>
          <div className="tag-row">{movie.genres.map((tag) => <span className="tag" key={tag.id}>{tag.name}</span>)}{countries.map((tag) => <span className="tag muted-tag" key={tag}>{tag}</span>)}</div>
          <div className="detail-actions">
            <button className="primary-button" onClick={() => openXiaoyaSearch(config.xiaoyaSearchBaseUrl, movie.title)} disabled={!config.xiaoyaSearchBaseUrl}>在小雅中搜索 <span>↗</span></button>
            <button className={"secondary-button " + (isFavorite ? "is-saved" : "")} onClick={() => void toggleFavorite()}>{isFavorite ? "♥ 已收藏" : "♡ 加入收藏"}</button>
            {movie.external_ids.imdb_id && <a className="secondary-button" href={"https://www.imdb.com/title/" + movie.external_ids.imdb_id + "/"} target="_blank" rel="noreferrer">IMDb ↗</a>}
          </div>
          {favoriteError && <div className="inline-error">{favoriteError}</div>}
          {directors.length > 0 && <section className="detail-section"><h3>导演</h3><p>{directors.join(" / ")}</p></section>}
          {actors.length > 0 && <section className="detail-section"><h3>主演</h3><p>{actors.join(" / ")}</p></section>}
          {movie.runtime && <section className="detail-section"><h3>片长</h3><p>{movie.runtime} 分钟</p></section>}
          {movie.number_of_seasons && <section className="detail-section"><h3>剧集信息</h3><p>{movie.number_of_seasons} 季 · {movie.number_of_episodes ?? "—"} 集</p></section>}
          <p className="tmdb-attribution">{movie.attribution}</p>
        </div>
      </section>
    </>
  );
}

function FavoritesPage() {
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [externalFavorites, setExternalFavorites] = useState<ExternalFavorite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function refresh() {
    setLoading(true);
    setError("");
    const [localResult, externalResult] = await Promise.allSettled([
      api.favorites(),
      api.externalFavorites()
    ]);
    if (localResult.status === "fulfilled") setFavorites(localResult.value);
    if (externalResult.status === "fulfilled") setExternalFavorites(externalResult.value);
    if (localResult.status === "rejected" && externalResult.status === "rejected") {
      setError((localResult.reason as Error).message || (externalResult.reason as Error).message);
    }
    setLoading(false);
  }

  useEffect(() => { void refresh(); }, []);

  async function removeLocal(movieId: number) {
    try {
      await api.removeFavorite(movieId);
      setFavorites((current) => current.filter((item) => item.movie.id !== movieId));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function removeExternal(mediaType: "movie" | "tv", providerId: number) {
    try {
      await api.removeExternalFavorite(mediaType, providerId);
      setExternalFavorites((current) => current.filter((item) => !(item.media_type === mediaType && item.provider_id === providerId)));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <PageHeading eyebrow="YOUR WATCHLIST" title="我的收藏" description="收藏记录长期保留；搜索和详情缓存过期不会影响你的收藏。" />
      {loading ? <Loading /> : error && favorites.length === 0 && externalFavorites.length === 0 ? <ErrorState message={error} /> : (
        <>
          {externalFavorites.length > 0 && (
            <>
              <div className="section-heading"><div><div className="eyebrow">ONLINE FAVORITES</div><h2>在线收藏</h2></div></div>
              <div className="movie-grid">
                {externalFavorites.map((favorite) => {
                  const item: DiscoveryItem = {
                    provider: "tmdb",
                    provider_id: favorite.provider_id,
                    media_type: favorite.media_type,
                    title: favorite.snapshot.title,
                    original_title: favorite.snapshot.original_title,
                    year: favorite.snapshot.year,
                    rating: favorite.snapshot.rating,
                    rating_count: favorite.snapshot.rating_count,
                    poster_path: favorite.snapshot.poster_path,
                    backdrop_path: favorite.snapshot.backdrop_path,
                    genre_ids: []
                  };
                  return (
                    <div className="favorite-card" key={favorite.media_type + ":" + favorite.provider_id}>
                      <ExternalMovieCard item={item} />
                      <button className="remove-favorite" onClick={() => void removeExternal(favorite.media_type, favorite.provider_id)}>移出收藏 ×</button>
                    </div>
                  );
                })}
              </div>
            </>
          )}
          {favorites.length > 0 && (
            <>
              <div className="section-heading"><div><div className="eyebrow">CHART FAVORITES</div><h2>榜单收藏</h2></div></div>
              <div className="movie-grid">
                {favorites.map((favorite) => (
                  <div className="favorite-card" key={favorite.movie.id}>
                    <MovieCard movie={favorite.movie} />
                    <button className="remove-favorite" onClick={() => void removeLocal(favorite.movie.id)}>移出收藏 ×</button>
                  </div>
                ))}
              </div>
            </>
          )}
          {favorites.length === 0 && externalFavorites.length === 0 && (
            <EmptyState title="收藏夹还是空的" detail="在在线作品或榜单详情页点击“加入收藏”，把想看的作品留在这里。" />
          )}
        </>
      )}
      <p className="tmdb-attribution">This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
    </>
  );
}

function NotFound() {
  return <EmptyState title="页面不存在" detail="返回发现页，重新开始探索。" />;
}

export default App;
