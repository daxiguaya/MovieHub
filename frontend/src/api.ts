import type {
  Chart,
  ChartMoviesResponse,
  ChartCompareResponse,
  ChartSnapshot,
  DiscoveryDetail,
  DiscoveryItem,
  DiscoverySearchResponse,
  ExternalFavorite,
  Favorite,
  MovieDetail,
  MoviesResponse
} from "./types";
import { appPath } from "./paths";

export function hasMovieHubApiKey(): boolean {
  if (typeof window === "undefined") return false;
  return Boolean(
    window.localStorage.getItem("moviehubApiKey") ||
    window.sessionStorage.getItem("moviehubApiKey")
  );
}

export function setMovieHubApiKey(value: string) {
  if (typeof window === "undefined") return;
  if (value.trim()) window.localStorage.setItem("moviehubApiKey", value.trim());
  else {
    window.localStorage.removeItem("moviehubApiKey");
    window.sessionStorage.removeItem("moviehubApiKey");
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let apiKey: string | null = null;
  if (typeof window !== "undefined") {
    apiKey = window.localStorage.getItem("moviehubApiKey");
    if (!apiKey) {
      apiKey = window.sessionStorage.getItem("moviehubApiKey");
      if (apiKey) {
        window.localStorage.setItem("moviehubApiKey", apiKey);
        window.sessionStorage.removeItem("moviehubApiKey");
      }
    }
  }
  const response = await fetch(appPath(`api${path}`), {
    ...init,
    headers: {
      Accept: "application/json",
      ...(apiKey ? { "X-API-Key": apiKey } : {}),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers
    }
  });

  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new Error(message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  charts: () => request<Chart[]>("/charts"),
  snapshots: (slug: string) =>
    request<ChartSnapshot[]>(`/charts/${encodeURIComponent(slug)}/snapshots`),
  compareChart: (slug: string, fromDate: string, toDate: string) => {
    const params = new URLSearchParams({ from_date: fromDate, to_date: toDate });
    return request<ChartCompareResponse>(
      `/charts/${encodeURIComponent(slug)}/compare?${params.toString()}`
    );
  },
  chart: (slug: string, snapshotDate?: string, cursor?: string) => {
    const params = new URLSearchParams();
    if (snapshotDate) params.set("snapshot_date", snapshotDate);
    if (cursor) params.set("cursor", cursor);
    const serialized = params.toString();
    const query = serialized ? `?${serialized}` : "";
    return request<ChartMoviesResponse>(
      `/charts/${encodeURIComponent(slug)}${query}`
    );
  },
  movies: (params: URLSearchParams) =>
    request<MoviesResponse>(`/movies?${params.toString()}`),
  movie: (movieId: number) =>
    request<MovieDetail>(`/movies/id/${movieId}`),
  favorites: () => request<Favorite[]>("/favorites"),
  discoverySearch: (query: string, mediaType: "all" | "movie" | "tv" = "all", page = 1) => {
    const params = new URLSearchParams({ q: query, media_type: mediaType, page: String(page) });
    return request<DiscoverySearchResponse>("/discovery/search?" + params.toString());
  },
  discoveryGenres: (mediaType: "movie" | "tv" = "movie") =>
    request<{ provider: string; media_type: string; genres: { id: number; name: string }[] }>(
      "/discovery/genres?media_type=" + mediaType
    ),
  discoveryRegions: () =>
    request<{ provider: string; regions: { code: string; name: string }[] }>("/discovery/regions"),
  discoveryDiscover: (params: URLSearchParams) =>
    request<DiscoverySearchResponse>("/discovery/discover?" + params.toString()),
  discoveryDetail: (mediaType: "movie" | "tv", providerId: number) =>
    request<DiscoveryDetail>("/discovery/" + mediaType + "/" + providerId),
  externalFavorites: () => request<ExternalFavorite[]>("/favorites/external"),
  externalFavoriteStatus: (
    mediaType: "movie" | "tv",
    providerId: number,
    imdbId?: string | null,
    identity?: { title: string; original_title: string | null; year: number | null; directors: string[] }
  ) => {
    const params = new URLSearchParams();
    if (imdbId) params.set("imdb_id", imdbId);
    if (identity) {
      params.set("title", identity.title);
      if (identity.original_title) params.set("original_title", identity.original_title);
      if (identity.year != null) params.set("year", String(identity.year));
      identity.directors.forEach((director) => params.append("directors", director));
    }
    const query = params.toString();
    return request<{ is_favorite: boolean }>(
      `/favorites/external/status/${mediaType}/${providerId}${query ? "?" + query : ""}`
    );
  },
  saveExternalFavorite: (item: DiscoveryDetail | DiscoveryItem) =>
    request<ExternalFavorite>("/favorites/external/" + item.media_type + "/" + item.provider_id, {
      method: "PUT",
      body: JSON.stringify({
        snapshot: {
          title: item.title,
          original_title: item.original_title,
          year: item.year,
          rating: item.rating,
          rating_count: item.rating_count,
          imdb_rating: item.imdb_rating ?? null,
          imdb_rating_count: item.imdb_rating_count ?? null,
          poster_path: item.poster_path,
          backdrop_path: item.backdrop_path,
          imdb_id: ("external_ids" in item ? item.external_ids.imdb_id : item.imdb_id) ?? null,
          directors: "credits" in item
            ? item.credits.crew?.filter((person) => person.job === "Director").map((person) => person.name) ?? []
            : []
        }
      })
    }),
  removeExternalFavorite: (
    mediaType: "movie" | "tv",
    providerId: number,
    imdbId?: string | null,
    identity?: { title: string; original_title: string | null; year: number | null; directors: string[] }
  ) => {
    const params = new URLSearchParams();
    if (imdbId) params.set("imdb_id", imdbId);
    if (identity) {
      params.set("title", identity.title);
      if (identity.original_title) params.set("original_title", identity.original_title);
      if (identity.year != null) params.set("year", String(identity.year));
      identity.directors.forEach((director) => params.append("directors", director));
    }
    const query = params.toString();
    return request<void>("/favorites/external/" + mediaType + "/" + providerId + (query ? "?" + query : ""), { method: "DELETE" });
  },
  addFavorite: (movieId: number, note = "") =>
    request<Favorite>(`/favorites/${movieId}`, {
      method: "PUT",
      body: JSON.stringify({ note })
    }),
  removeFavorite: (movieId: number) =>
    request<void>(`/favorites/${movieId}`, { method: "DELETE" })
};
