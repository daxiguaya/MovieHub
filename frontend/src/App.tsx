import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams
} from "react-router-dom";
import { api, setMovieHubApiKey } from "./api";
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
    xiaoyaSearchUrlTemplate: ""
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
          <Route path="/credits" element={<CreditsPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="site-footer">
        <span>MovieHub</span>
        <span>发现好电影，剩下的交给小雅与 Jellyfin。</span>
        <Link to="/credits">关于与数据来源</Link>
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

type FilterOption = { value: string; label: string };

function MultiSelectFilter({
  label, options, value, onChange, searchPlaceholder
}: {
  label: string;
  options: FilterOption[];
  value: string[];
  onChange: (next: string[]) => void;
  searchPlaceholder: string;
}) {
  const [query, setQuery] = useState("");
  const filtered = options.filter((option) =>
    option.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  );
  return (
    <details className="multi-filter">
      <summary>
        <span>{label}</span>
        <span className="multi-filter-count">{value.length ? `已选 ${value.length} 项` : "不限"} <span aria-hidden="true">⌄</span></span>
      </summary>
      <div className="multi-filter-panel">
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
        />
        <div className="multi-filter-options">
          {filtered.map((option) => (
            <label className="multi-filter-option" key={option.value}>
              <input
                type="checkbox"
                checked={value.includes(option.value)}
                onChange={(event) => onChange(
                  event.target.checked
                    ? [...value, option.value]
                    : value.filter((item) => item !== option.value)
                )}
              />
              <span>{option.label}</span>
            </label>
          ))}
          {filtered.length === 0 && <p className="multi-filter-empty">没有匹配的选项</p>}
        </div>
        {value.length > 0 && (
          <button className="multi-filter-clear" type="button" onClick={() => onChange([])}>清空已选</button>
        )}
      </div>
    </details>
  );
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
    const definitions = Object.entries(DISCOVERY_LISTS);
    Promise.all(definitions.map(async ([key, definition]) => {
      const params = new URLSearchParams({
        media_type: "movie",
        page: "1",
        with_genres: definition.genre,
        min_votes: String(definition.minVotes),
        min_rating: String(definition.minRating),
        sort_by: "vote_average.desc"
      });
      if (definition.maxVotes) params.set("max_votes", String(definition.maxVotes));
      const data = await api.discoveryDiscover(params);
      return { key, title: definition.title, items: data.items.slice(0, 5) };
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
                  <span className="spotlight-item-copy"><strong>{item.title}</strong><small>{item.year ?? "年份未知"} · TMDB ★ {item.rating?.toFixed(1) ?? "—"} · {item.rating_count.toLocaleString()} 票</small></span>
                </Link>
              ))}
              {list.items.length === 0 && <p className="spotlight-empty">暂无符合条件的作品</p>}
              <Link className="spotlight-more" to={"/discover/" + list.key}>查看完整榜单 <span>→</span></Link>
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

function MovieCard({ movie, rank, localMatch = false }: { movie: Movie; rank?: number; localMatch?: boolean }) {
  return (
    <article className="movie-card">
      <MoviePoster movie={movie} rank={rank} />
      <div className="movie-card-info">
        <Link to={`/movies/${movie.id}`} className="movie-title">{movie.title}</Link>
        <div className="movie-subtitle">{movie.year ?? "年份未知"} · {movie.type === "tv" ? "剧集" : "电影"}</div>
        {localMatch && <div className="movie-subtitle">本地榜单收录</div>}
        <div className="movie-rating"><span>★</span> 豆瓣 {movie.rating?.toFixed(1) ?? "暂无评分"} <small>({movie.rating_count == null ? "暂无评价人数" : movie.rating_count.toLocaleString()})</small></div>
      </div>
    </article>
  );
}


function ExternalMovieCard({ item, localMovie }: { item: DiscoveryItem; localMovie?: Movie }) {
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
        {localMovie && <div className="movie-subtitle">本地榜单收录 · 豆瓣 {localMovie.rating?.toFixed(1) ?? "暂无评分"}</div>}
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
  const [selectedGenres, setSelectedGenres] = useState<string[]>(searchParams.get("genre_ids")?.split(/[|,]/) ?? []);
  const [selectedRegions, setSelectedRegions] = useState<string[]>(searchParams.get("region_codes")?.split("|") ?? []);
  const [results, setResults] = useState<Movie[]>([]);
  const [onlineResults, setOnlineResults] = useState<DiscoveryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [onlineTotal, setOnlineTotal] = useState(0);
  const [onlinePage, setOnlinePage] = useState(1);
  const [onlinePages, setOnlinePages] = useState(0);
  const [resolvedLocalTmdbIds, setResolvedLocalTmdbIds] = useState<Record<number, string>>({});
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
    const requestedType = (params.get("type") as "all" | "movie" | "tv" | null) ?? "all";
    const requestedMinRating = params.get("min_rating") ?? "";
    const requestedMinYear = params.get("min_year") ?? "";
    const requestedMaxYear = params.get("max_year") ?? "";
    const selectedGenreIds = (params.get("genre_ids") ?? "").split(/[|,]/).filter(Boolean);
    const selectedRegionCodes = (params.get("region_codes") ?? "").split("|").filter(Boolean);
    const requestedPage = appendOnline ? onlinePage + 1 : 1;
    // TMDB genre filters use comma for AND; normalize legacy pipe-separated URLs.
    const genreIds = selectedGenreIds.join(",");
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
      if (requestedType !== "all") localParams.set("type", requestedType);
      if (params.get("min_rating")) localParams.set("min_rating", params.get("min_rating")!);
      if (params.get("min_rating_count")) localParams.set("min_rating_count", params.get("min_rating_count")!);
      if (params.get("min_year")) localParams.set("min_year", params.get("min_year")!);
      if (params.get("max_year")) localParams.set("max_year", params.get("max_year")!);
      const [resolvedGenreOptions, resolvedRegionOptions] = await Promise.all([
        selectedGenreIds.length
          ? api.discoveryGenres(requestedType === "tv" ? "tv" : "movie").then((data) => data.genres)
          : Promise.resolve(genreOptions),
        selectedRegionCodes.length && !regionOptions.length
          ? api.discoveryRegions().then((data) => data.regions)
          : Promise.resolve(regionOptions)
      ]);
      if (selectedGenreIds.length && resolvedGenreOptions.length) setGenreOptions(resolvedGenreOptions);
      if (selectedRegionCodes.length && resolvedRegionOptions.length) setRegionOptions(resolvedRegionOptions);
      const genreNames = selectedGenreIds.map((id) => resolvedGenreOptions.find((item) => String(item.id) === id)?.name).filter(Boolean);
      const regionNames = selectedRegionCodes.map((code) => resolvedRegionOptions.find((item) => item.code === code)?.name).filter(Boolean);
      if (genreNames.length) localParams.set("genres", genreNames.join(","));
      if (regionNames.length) localParams.set("regions", regionNames.join(","));
      const hasLocalCriteria = localParams.toString().length > 0;

      const localPromise = hasLocalCriteria
        ? api.movies(localParams)
        : Promise.resolve({ items: [] as Movie[], total: 0, next_cursor: null as string | null });

      let onlinePromise: Promise<import("./types").DiscoverySearchResponse> | null = null;
      if (q.length >= 2) {
        onlinePromise = api.discoverySearch(q, requestedType, requestedPage);
      } else if (hasFilters) {
        const discoverParams = new URLSearchParams({
          media_type: requestedType === "tv" ? "tv" : "movie",
          page: String(requestedPage),
          min_votes: params.get("min_rating_count") || "100",
          sort_by: requestedMinRating ? "vote_average.desc" : "popularity.desc"
        });
        if (genreIds) discoverParams.set("with_genres", genreIds);
        if (selectedRegionCodes.length) discoverParams.set("region", selectedRegionCodes.join("|"));
        if (requestedMinRating) discoverParams.set("min_rating", requestedMinRating);
        if (requestedMinYear) discoverParams.set("min_year", requestedMinYear);
        if (requestedMaxYear) discoverParams.set("max_year", requestedMaxYear);
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
    const params = new URLSearchParams(searchParams);
    setKeyword(params.get("search") ?? "");
    setType((params.get("type") as "all" | "movie" | "tv" | null) ?? "all");
    setMinRating(params.get("min_rating") ?? "");
    setMinRatingCount(params.get("min_rating_count") ?? "100");
    setMinYear(params.get("min_year") ?? "");
    setMaxYear(params.get("max_year") ?? "");
    setSelectedGenres((params.get("genre_ids") ?? "").split(/[|,]/).filter(Boolean));
    setSelectedRegions((params.get("region_codes") ?? "").split("|").filter(Boolean));
    if (params.toString()) void runSearch(params);
    else {
      setResults([]);
      setOnlineResults([]);
      setTotal(0);
      setOnlineTotal(0);
      setHasSearched(false);
    }
    // URL is the single source of truth for search state, including browser back/forward.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  useEffect(() => {
    let active = true;
    const normalize = (value: string | null | undefined) =>
      (value ?? "").normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
    const candidates = results.filter((movie) => {
      if (movie.tmdb_id || movie.imdb_id || movie.year == null) return false;
      const localTitles = [movie.title, movie.original_title].map(normalize).filter(Boolean);
      return onlineResults.some((item) =>
        item.media_type === movie.type &&
        item.year === movie.year &&
        localTitles.some((title) =>
          [item.title, item.original_title].map(normalize).filter(Boolean).includes(title)
        )
      );
    });
    setResolvedLocalTmdbIds({});
    if (!candidates.length) return () => { active = false; };
    void Promise.all(candidates.map(async (movie) => {
      try {
        const detail = await api.movie(movie.id);
        const providerId = detail.tmdb_metadata?.provider_id;
        return typeof providerId === "number" && providerId > 0
          ? [movie.id, String(providerId)] as const
          : null;
      } catch {
        return null;
      }
    })).then((matches) => {
      if (active) {
        setResolvedLocalTmdbIds(Object.fromEntries(matches.filter(
          (match): match is readonly [number, string] => match !== null
        )));
      }
    });
    return () => { active = false; };
  }, [results, onlineResults]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (keyword.trim()) params.set("search", keyword.trim());
    if (type !== "all") params.set("type", type);
    if (minRating) params.set("min_rating", minRating);
    if (minRatingCount) params.set("min_rating_count", minRatingCount);
    if (minYear) params.set("min_year", minYear);
    if (maxYear) params.set("max_year", maxYear);
    if (selectedGenres.length) params.set("genre_ids", selectedGenres.join(","));
    if (selectedRegions.length) params.set("region_codes", selectedRegions.join("|"));
    setSearchParams(params);
  }

  async function loadMoreLocal() {
    if (!nextCursor || loading) return;
    const state = new URLSearchParams(searchParams);
    const genreIds = (state.get("genre_ids") ?? "").split(/[|,]/).filter(Boolean);
    const regionCodes = (state.get("region_codes") ?? "").split("|").filter(Boolean);
    setLoading(true);
    try {
      const [genres, regions] = await Promise.all([
        genreIds.length
          ? api.discoveryGenres(state.get("type") === "tv" ? "tv" : "movie").then((data) => data.genres)
          : Promise.resolve(genreOptions),
        regionCodes.length && !regionOptions.length
          ? api.discoveryRegions().then((data) => data.regions)
          : Promise.resolve(regionOptions)
      ]);
      const params = new URLSearchParams();
      if (state.get("search")) params.set("search", state.get("search")!);
      if (state.get("type") && state.get("type") !== "all") params.set("type", state.get("type")!);
      for (const key of ["min_rating", "min_rating_count", "min_year", "max_year"]) {
        if (state.get(key)) params.set(key, state.get(key)!);
      }
      const genreNames = genreIds.map((id) => genres.find((item) => String(item.id) === id)?.name).filter(Boolean);
      const regionNames = regionCodes.map((code) => regions.find((item) => item.code === code)?.name).filter(Boolean);
      if (genreNames.length) params.set("genres", genreNames.join(","));
      if (regionNames.length) params.set("regions", regionNames.join(","));
      params.set("cursor", nextCursor);
      const data = await api.movies(params);
      setGenreOptions(genres);
      setRegionOptions(regions);
      setResults((current) => current.concat(data.items));
      setNextCursor(data.next_cursor);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function loadMoreOnline() {
    if (onlinePage >= onlinePages || loading) return;
    const nextPage = onlinePage + 1;
    const q = (searchParams.get("search") ?? "").trim();
    const requestedType = (searchParams.get("type") as "all" | "movie" | "tv" | null) ?? "all";
    const requestedMinRating = searchParams.get("min_rating") ?? "";
    const request = q.length >= 2
      ? api.discoverySearch(q, requestedType, nextPage)
      : api.discoveryDiscover(new URLSearchParams({
          media_type: requestedType === "tv" ? "tv" : "movie",
          page: String(nextPage),
          min_votes: searchParams.get("min_rating_count") || "100",
          sort_by: requestedMinRating ? "vote_average.desc" : "popularity.desc",
          ...(searchParams.get("genre_ids") ? { with_genres: searchParams.get("genre_ids")!.split(/[|,]/).filter(Boolean).join(",") } : {}),
          ...(searchParams.get("region_codes") ? { region: searchParams.get("region_codes")! } : {}),
          ...(requestedMinRating ? { min_rating: requestedMinRating } : {}),
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

  // Only stable provider IDs establish identity; same title/year alone can be different films.
  const findLinkedLocalMovie = (item: DiscoveryItem) => results.find((movie) =>
    movie.type === item.media_type && (
      movie.tmdb_id === String(item.provider_id) ||
      Boolean(item.imdb_id && movie.imdb_id && movie.imdb_id === item.imdb_id) ||
      resolvedLocalTmdbIds[movie.id] === String(item.provider_id)
    )
  );
  const localOnly = results.filter((movie) => !onlineResults.some((item) =>
    movie.type === item.media_type && (
      movie.tmdb_id === String(item.provider_id) ||
      Boolean(item.imdb_id && movie.imdb_id && movie.imdb_id === item.imdb_id) ||
      resolvedLocalTmdbIds[movie.id] === String(item.provider_id)
    )
  ));

  return (
    <>
      <PageHeading eyebrow="ONLINE DISCOVERY" title="搜索全网电影与剧集" description="在线搜索 TMDB 的电影和剧集目录；搜索结果按页加载，不会把全站资料一次性下载到 NAS。" />
      <form className="search-panel" onSubmit={submit}>
        <label className="search-input"><span>⌕</span><input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="输入片名，例如：异形、蝙蝠侠…" /></label>
        <label>影视类型<select value={type} onChange={(e) => setType(e.target.value as "all" | "movie" | "tv")}><option value="all">全部（关键词搜索）</option><option value="movie">电影</option><option value="tv">剧集</option></select></label>
        <label>最低 TMDB 评分<select value={minRating} onChange={(e) => setMinRating(e.target.value)}><option value="">不限</option><option value="5">5.0+</option><option value="6">6.0+</option><option value="7">7.0+</option><option value="8">8.0+</option></select></label>
        <label>最低投票数<input type="number" min="0" max="10000000" value={minRatingCount} onChange={(e) => setMinRatingCount(e.target.value)} placeholder="默认 100" /></label>
        <label>起始年份<input type="number" min="1870" max="2100" value={minYear} onChange={(e) => setMinYear(e.target.value)} placeholder="例如 2000" /></label>
        <label>结束年份<input type="number" min="1870" max="2100" value={maxYear} onChange={(e) => setMaxYear(e.target.value)} placeholder="例如 2026" /></label>
        <div className="search-filter">
          <MultiSelectFilter
            label="类型（可多选）"
            options={genreOptions.map((genre) => ({ value: String(genre.id), label: genre.name }))}
            value={selectedGenres}
            onChange={setSelectedGenres}
            searchPlaceholder="搜索类型，例如：恐怖、悬疑…"
          />
        </div>
        <div className="search-filter">
          <MultiSelectFilter
            label="制作国家/地区（可多选）"
            options={regionOptions.map((region) => ({ value: region.code, label: region.name }))}
            value={selectedRegions}
            onChange={setSelectedRegions}
            searchPlaceholder="搜索国家或地区…"
          />
        </div>
        <button className="primary-button" type="submit">搜索 / 筛选 <span>→</span></button>
      </form>
      <p className="search-hint">类型和制作国家/地区支持直接勾选及关键词查找，无需按住 Ctrl。多个类型必须同时符合（AND）；关键词搜索按片名匹配，组合筛选请清空关键词后使用。</p>
      <div className="result-caption"><span>在线搜索结果</span><span>{onlineTotal.toLocaleString()} 部 · 本地匹配 {total.toLocaleString()} 部 · 当前第 {onlinePage || 1} 页</span></div>
      {onlineError && <div className="inline-error">{onlineError}</div>}
      {error && <div className="inline-error">{error}</div>}
      {onlineResults.length > 0 || localOnly.length > 0 ? (
        <>
          <div className="movie-grid">
            {onlineResults.map((item) => <ExternalMovieCard key={item.media_type + ":" + item.provider_id} item={item} localMovie={findLinkedLocalMovie(item)} />)}
            {localOnly.map((movie) => <MovieCard key={"local:" + movie.id} movie={movie} localMatch />)}
          </div>
          {nextCursor && <button className="secondary-button load-more" onClick={loadMoreLocal}>加载更多本地匹配</button>}
          {onlinePage < onlinePages && <button className="secondary-button load-more" onClick={loadMoreOnline} disabled={loading}>{loading ? "正在加载…" : "加载更多在线结果"}</button>}
        </>
      ) : loading ? <Loading /> : hasSearched ? (
        <EmptyState title="没有找到匹配的作品" detail="试试更短的片名，或放宽类型、地区、年份和评分条件。" />
      ) : (
        <EmptyState title="输入片名或选择筛选条件" detail="关键词搜索覆盖在线电影和剧集；不输入关键词时，可以使用类型、地区、年份和评分发现作品。" />
      )}

      <p className="tmdb-attribution">This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
    </>
  );
}

function DetailBackButton() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <button
      className="secondary-button detail-back-button"
      type="button"
      onClick={() => { if (location.key === "default") navigate("/search"); else navigate(-1); }}
    >
      <span aria-hidden="true">←</span> 返回上一页
    </button>
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
      .then((data) => {
        if (!active) return;
        setMovie(data);
        if (data.tmdb_id) {
          void api.externalFavoriteStatus(data.type, Number(data.tmdb_id), data.imdb_id)
            .then((result) => { if (active) setIsFavorite(result.is_favorite); })
            .catch(() => undefined);
        } else {
          void api.favorites()
            .then((items) => { if (active) setIsFavorite(items.some((item) => item.movie.id === id)); })
            .catch(() => undefined);
        }
      })
      .catch((err: Error) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id]);

  async function toggleFavorite() {
    if (!movie) return;
    setFavoriteError("");
    try {
      if (isFavorite && movie.tmdb_id) await api.removeExternalFavorite(movie.type, Number(movie.tmdb_id), movie.imdb_id);
      else if (isFavorite) await api.removeFavorite(movie.id);
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
      <DetailBackButton />
      <div className="breadcrumb"><Link to="/">发现</Link><span>/</span><Link to="/search">全网搜索</Link><span>/</span><span>{movie.title}</span></div>
      <section className="detail-layout">
        <div className="detail-poster-wrap">
          <MoviePoster movie={movie} />
          <div className="detail-poster-caption">MOVIEHUB COLLECTION</div>
        </div>
        <div className="detail-copy">
          <div className="eyebrow">{movie.type === "tv" ? "TELEVISION SERIES" : "FEATURE FILM"} · {movie.year ?? movie.tmdb_metadata?.year ?? "YEAR UNKNOWN"}</div>
          <h1>{movie.title}</h1>
          {movie.original_title && <div className="original-title">{movie.original_title}</div>}
          <div className="detail-rating"><strong>★ {movie.rating?.toFixed(1) ?? "暂无评分"}</strong><span>豆瓣 · {movie.rating_count == null ? "暂无评价人数" : `${movie.rating_count.toLocaleString()} 人评价`}</span>
            {movie.tmdb_metadata?.rating != null && <span>TMDB · ★ {movie.tmdb_metadata.rating.toFixed(1)} · {movie.tmdb_metadata.rating_count.toLocaleString()} 票</span>}
          </div>
          <div className="tag-row">{(movie.genres.length ? movie.genres : movie.tmdb_metadata?.genres ?? []).map((tag) => <span className="tag" key={tag}>{tag}</span>)}{(movie.regions.length ? movie.regions : movie.tmdb_metadata?.regions ?? []).map((tag) => <span className="tag muted-tag" key={tag}>{tag}</span>)}</div>
          {movie.tmdb_metadata && <p className="detail-source-note">缺失的年份、类型、地区及演职员资料由 TMDB 补充；豆瓣与 TMDB 评分分别展示。</p>}
          <div className="detail-actions">
            <button className="primary-button" onClick={() => openXiaoyaSearch(config.xiaoyaSearchUrlTemplate, movie.title)} disabled={!config.xiaoyaSearchUrlTemplate}>在小雅中搜索 <span>↗</span></button>
            <button className={`secondary-button ${isFavorite ? "is-saved" : ""}`} onClick={() => void toggleFavorite()}>{isFavorite ? "♥ 已收藏" : "♡ 加入收藏"}</button>
            {movie.douban_url && <a className="secondary-button" href={movie.douban_url} target="_blank" rel="noreferrer">豆瓣资料 ↗</a>}
          </div>
          {favoriteError && <div className="inline-error">{favoriteError} · <Link to="/favorites">前往收藏页连接 API Key</Link></div>}
          {(movie.overview || movie.tmdb_metadata?.overview) && <section className="detail-section"><h3>剧情简介{!movie.overview && movie.tmdb_metadata?.overview ? " · TMDB" : ""}</h3><p>{movie.overview || movie.tmdb_metadata?.overview}</p></section>}
          {(movie.directors.length || movie.tmdb_metadata?.directors.length || 0) > 0 && <section className="detail-section"><h3>导演</h3><p>{(movie.directors.length ? movie.directors : movie.tmdb_metadata?.directors ?? []).join(" / ")}</p></section>}
          {(movie.actors.length || movie.tmdb_metadata?.actors.length || 0) > 0 && <section className="detail-section"><h3>主演</h3><p>{(movie.actors.length ? movie.actors : movie.tmdb_metadata?.actors ?? []).join(" / ")}</p></section>}
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
      .then((data) => {
        if (!active) return;
        setMovie(data);
        void api.externalFavoriteStatus(validType, id, data.external_ids.imdb_id, {
          title: data.title,
          original_title: data.original_title,
          year: data.year,
          directors: data.credits.crew?.filter((person) => person.job === "Director").map((person) => person.name) ?? []
        })
          .then((result) => { if (active) setIsFavorite(result.is_favorite); })
          .catch(() => undefined);
      })
      .catch((err: Error) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, mediaType, validType]);

  async function toggleFavorite() {
    if (!movie) return;
    setFavoriteError("");
    try {
      if (isFavorite) await api.removeExternalFavorite(validType, id, movie.external_ids.imdb_id, {
        title: movie.title,
        original_title: movie.original_title,
        year: movie.year,
        directors: movie.credits.crew?.filter((person) => person.job === "Director").map((person) => person.name) ?? []
      });
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
      <DetailBackButton />
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
            <button className="primary-button" onClick={() => openXiaoyaSearch(config.xiaoyaSearchUrlTemplate, movie.title)} disabled={!config.xiaoyaSearchUrlTemplate}>在小雅中搜索 <span>↗</span></button>
            <button className={"secondary-button " + (isFavorite ? "is-saved" : "")} onClick={() => void toggleFavorite()}>{isFavorite ? "♥ 已收藏" : "♡ 加入收藏"}</button>
            {movie.external_ids.imdb_id && <a className="secondary-button" href={"https://www.imdb.com/title/" + movie.external_ids.imdb_id + "/"} target="_blank" rel="noreferrer">IMDb ↗</a>}
          </div>
          {favoriteError && <div className="inline-error">{favoriteError} · <Link to="/favorites">前往收藏页连接 API Key</Link></div>}
          {movie.overview && <section className="detail-section"><h3>剧情简介</h3><p>{movie.overview}</p></section>}
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
  const [apiKeyInput, setApiKeyInput] = useState("");

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

  function connectApiKey(event: FormEvent) {
    event.preventDefault();
    setMovieHubApiKey(apiKeyInput);
    setApiKeyInput("");
    void refresh();
  }

  async function removeLocal(movieId: number) {
    try {
      await api.removeFavorite(movieId);
      const removed = favorites.find((item) => item.movie.id === movieId)?.movie;
      setFavorites((current) => current.filter((item) => item.movie.id !== movieId));
      if (removed) {
        setExternalFavorites((current) => current.filter((item) =>
          item.media_type !== removed.type ||
          (removed.tmdb_id !== String(item.provider_id) &&
            !(removed.imdb_id && removed.imdb_id === item.snapshot.imdb_id))
        ));
      }
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
      {loading ? <Loading /> : error && (error.toLowerCase().includes("api key") || error.toLowerCase().includes("api_key")) ? (
        <section className="api-key-gate">
          <h2>连接收藏功能</h2>
          <p>收藏接口受 MovieHub API Key 保护。密钥保存在当前浏览器的本地存储中，多个标签页共用；不会发送给 TMDB 或其他第三方。</p>
          <form onSubmit={connectApiKey}>
            <input type="password" value={apiKeyInput} onChange={(event) => setApiKeyInput(event.target.value)} placeholder="输入 NAS 上配置的 MovieHub API Key" autoComplete="off" />
            <button className="primary-button" type="submit" disabled={!apiKeyInput.trim()}>连接收藏</button>
          </form>
          <small>{error}</small>
        </section>
      ) : error && favorites.length === 0 && externalFavorites.length === 0 ? <ErrorState message={error} /> : (
        <>
          {externalFavorites.filter((item) => !favorites.some((favorite) =>
        favorite.movie.type === item.media_type && (favorite.movie.tmdb_id === String(item.provider_id) || Boolean(favorite.movie.imdb_id && favorite.movie.imdb_id === item.snapshot.imdb_id))
      )).length > 0 && (
            <>
              <div className="section-heading"><div><div className="eyebrow">ONLINE FAVORITES</div><h2>在线收藏</h2></div></div>
              <div className="movie-grid">
                {externalFavorites.filter((item) => !favorites.some((favorite) =>
                  favorite.movie.type === item.media_type && (favorite.movie.tmdb_id === String(item.provider_id) || Boolean(favorite.movie.imdb_id && favorite.movie.imdb_id === item.snapshot.imdb_id))
                )).map((favorite) => {
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

function CreditsPage() {
  return (
    <>
      <PageHeading eyebrow="ABOUT & CREDITS" title="关于与数据来源" description="MovieHub 使用公开数据服务辅助电影与剧集发现；各数据来源保持独立标注。" />
      <section className="credits-panel">
        <a className="tmdb-logo-link" href="https://www.themoviedb.org" target="_blank" rel="noreferrer">
          <img
            src="https://www.themoviedb.org/assets/2/v4/logos/v2/blue_square_2-d537fb228cf3ded904ef09b136fe3fec72548ebc1fea3fbbd1ad9e36364db38b.svg"
            alt="The Movie Database (TMDB)"
          />
        </a>
        <div className="credits-copy">
          <h2>The Movie Database (TMDB)</h2>
          <p>This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
          <a href="https://www.themoviedb.org" target="_blank" rel="noreferrer">Visit The Movie Database ↗</a>
        </div>
      </section>
      <section className="credits-panel">
        <div className="credits-copy">
          <h2>豆瓣</h2>
          <p>现有豆瓣榜单数据按榜单来源单独展示。MovieHub 不代表豆瓣官方，也不将豆瓣评分与 TMDB 评分合并。</p>
          <a href="https://movie.douban.com" target="_blank" rel="noreferrer">访问豆瓣电影 ↗</a>
        </div>
      </section>
    </>
  );
}

function NotFound() {
  return <EmptyState title="页面不存在" detail="返回发现页，重新开始探索。" />;
}

export default App;
