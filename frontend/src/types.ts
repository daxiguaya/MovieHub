export interface Chart {
  list_id: number;
  slug: string;
  name: string;
  source: string;
  category: string;
  period: string | null;
  description: string | null;
  enabled: boolean;
  display_order: number;
  last_updated: string | null;
}

export interface Movie {
  id: number;
  douban_id: string | null;
  tmdb_id?: string | null;
  title: string;
  original_title: string | null;
  year: number | null;
  rating: number | null;
  rating_count: number;
  type: "movie" | "tv";
  genres: string[];
  regions: string[];
  updated_at: number | null;
}

export interface MovieDetail extends Movie {
  imdb_id: string | null;
  tmdb_id: string | null;
  directors: string[];
  actors: string[];
  overview: string | null;
  douban_url: string | null;
  posters: string[];
}

export interface ChartMovie extends Movie {
  rank: number;
  source_rating: number | null;
  snapshot_date: string;
}

export interface ChartMoviesResponse {
  chart: Chart;
  items: ChartMovie[];
  next_cursor: string | null;
  total: number;
}

export interface ChartSnapshot {
  snapshot_date: string;
  imported_at: string;
  item_count: number;
}

export interface MoviesResponse {
  items: Movie[];
  next_cursor: string | null;
  total: number;
}

export interface Favorite {
  movie: Movie;
  created_at: string;
  note: string;
}

export interface PublicConfig {
  xiaoyaSearchBaseUrl: string;
}

export interface ChartRankChange {
  movie_id: number;
  douban_id: string | null;
  title: string;
  year: number | null;
  type: "movie" | "tv";
  before_rank: number | null;
  after_rank: number | null;
  rank_change: number | null;
  status: "new" | "removed" | "moved" | "unchanged";
}

export interface ChartCompareResponse {
  chart: Chart;
  from_date: string;
  to_date: string;
  total_before: number;
  total_after: number;
  items: ChartRankChange[];
}


export interface DiscoveryItem {
  provider: "tmdb";
  provider_id: number;
  media_type: "movie" | "tv";
  title: string;
  original_title: string | null;
  year: number | null;
  rating: number | null;
  rating_count: number;
  poster_path: string | null;
  backdrop_path: string | null;
  genre_ids: number[];
}

export interface DiscoverySearchResponse {
  provider: "tmdb";
  query?: string;
  media_type?: "movie" | "tv";
  page: number;
  total_pages: number;
  total_results: number;
  items: DiscoveryItem[];
  attribution: string;
}

export interface ExternalFavorite {
  provider: "tmdb";
  media_type: "movie" | "tv";
  provider_id: number;
  snapshot: Pick<DiscoveryItem, "title" | "original_title" | "year" | "rating" | "rating_count" | "poster_path" | "backdrop_path">;
  note: string;
  created_at: number;
  updated_at: number;
}

export interface DiscoveryDetail extends DiscoveryItem {
  genres: { id: number; name: string }[];
  production_countries: { iso_3166_1?: string; name?: string }[] | string[];
  runtime: number | null;
  number_of_seasons: number | null;
  number_of_episodes: number | null;
  credits: { crew?: { id: number; name: string; job: string }[]; cast?: { id: number; name: string; character: string }[] };
  external_ids: { imdb_id?: string; tvdb_id?: number };
  attribution: string;
}
