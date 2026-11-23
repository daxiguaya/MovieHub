import { useEffect, useMemo, useState } from "react";
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
import type {
  Chart,
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
          <NavLink to="/search">电影库</NavLink>
          <NavLink to="/favorites">我的收藏</NavLink>
        </nav>
        <Link className="top-search" to="/search" aria-label="搜索电影">
          <span>⌕</span><span className="top-search-label">搜索电影</span>
          <kbd>⌘ K</kbd>
        </Link>
      </header>

      <main className="page-container">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/charts/:slug" element={<ChartPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/movies/:movieId" element={<MoviePage config={publicConfig} />} />
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
  action?: React.ReactNode;
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

function ChartTile({ chart }: { chart: Chart }) {
  const descriptions: Record<string, string> = {
    top250: "影史经典，历久弥新",
    popular: "此刻正在被讨论",
    "high-rated": "口碑与评分兼顾",
    "annual-2025": "回看 2025 的银幕记忆",
    "annual-2026": "记录 2026 的精彩作品"
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
          src={`/api/movies/${movie.id}/poster`}
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

  useEffect(() => {
    let active = true;
    setLoading(true);
    setItems([]);
    setSnapshotDate("");
    Promise.all([api.snapshots(slug), api.chart(slug)])
      .then(([history, latest]) => {
        if (!active) return;
        setSnapshots(history);
        setSnapshotDate(history[0]?.snapshot_date ?? "");
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
    </>
  );
}

function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [keyword, setKeyword] = useState(searchParams.get("search") ?? "");
  const [type, setType] = useState(searchParams.get("type") ?? "");
  const [minRating, setMinRating] = useState(searchParams.get("min_rating") ?? "");
  const [minYear, setMinYear] = useState(searchParams.get("min_year") ?? "");
  const [sortBy, setSortBy] = useState(searchParams.get("sort_by") ?? "rating_count");
  const [results, setResults] = useState<Movie[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function runSearch(params: URLSearchParams) {
    setLoading(true);
    setError("");
    try {
      const data = await api.movies(params);
      setResults(data.items);
      setTotal(data.total);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(searchParams);
    void runSearch(params);
    // Search is intentionally driven by the URL query string.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams();
    if (keyword.trim()) params.set("search", keyword.trim());
    if (type) params.set("type", type);
    if (minRating) params.set("min_rating", minRating);
    if (minYear) params.set("min_year", minYear);
    params.set("sort_by", sortBy);
    setSearchParams(params);
    void runSearch(params);
  }

  return (
    <>
      <PageHeading eyebrow="MOVIE LIBRARY" title="找到下一部想看的" description="按片名、年份、类型和评分筛选 MovieHub 已收录的电影与剧集。" />
      <form className="search-panel" onSubmit={submit}>
        <label className="search-input"><span>⌕</span><input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索中文片名或原名…" /></label>
        <label>类型<select value={type} onChange={(e) => setType(e.target.value)}><option value="">全部</option><option value="movie">电影</option><option value="tv">剧集</option></select></label>
        <label>最低评分<select value={minRating} onChange={(e) => setMinRating(e.target.value)}><option value="">不限</option><option value="6">6.0+</option><option value="7">7.0+</option><option value="8">8.0+</option><option value="9">9.0+</option></select></label>
        <label>年份<input type="number" min="1870" max="2200" value={minYear} onChange={(e) => setMinYear(e.target.value)} placeholder="起始年份" /></label>
        <label>排序<select value={sortBy} onChange={(e) => setSortBy(e.target.value)}><option value="rating_count">热度</option><option value="rating">评分</option><option value="year">年份</option></select></label>
        <button className="primary-button" type="submit">搜索电影 <span>→</span></button>
      </form>
      <div className="result-caption"><span>搜索结果</span><span>{total.toLocaleString()} 部作品</span></div>
      {loading ? <Loading /> : error ? <ErrorState message={error} /> : results.length === 0 ? (
        <EmptyState title="没有找到匹配的电影" detail="试试更短的片名，或放宽评分与年份条件。" />
      ) : <div className="movie-grid">{results.map((movie) => <MovieCard key={movie.id} movie={movie} />)}</div>}
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

function FavoritesPage() {
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      setFavorites(await api.favorites());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function remove(movieId: number) {
    try {
      await api.removeFavorite(movieId);
      setFavorites((current) => current.filter((item) => item.movie.id !== movieId));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <PageHeading eyebrow="YOUR WATCHLIST" title="我的收藏" description="把想看的电影留在这里，等有空时再慢慢探索。" />
      {loading ? <Loading /> : error ? <ErrorState message={error} /> : favorites.length === 0 ? (
        <EmptyState title="收藏夹还是空的" detail="在电影详情页点击“加入收藏”，把想看的作品收集起来。" />
      ) : (
        <div className="movie-grid">
          {favorites.map((favorite) => (
            <div className="favorite-card" key={favorite.movie.id}>
              <MovieCard movie={favorite.movie} />
              <button className="remove-favorite" onClick={() => void remove(favorite.movie.id)}>移出收藏 ×</button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function NotFound() {
  return <EmptyState title="页面不存在" detail="返回发现页，重新开始探索。" />;
}

export default App;
