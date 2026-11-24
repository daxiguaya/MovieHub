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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(appPath(`api${path}`), {
    ...init,
    headers: {
      Accept: "application/json",
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
  discoveryDetail: (mediaType: "movie" | "tv", providerId: number) =>
    request<DiscoveryDetail>("/discovery/" + mediaType + "/" + providerId),
  externalFavorites: () => request<ExternalFavorite[]>("/discovery/favorites"),
  saveExternalFavorite: (item: DiscoveryDetail | DiscoveryItem) =>
    request<ExternalFavorite>("/discovery/favorites/" + item.media_type + "/" + item.provider_id, {
      method: "PUT",
      body: JSON.stringify({
        snapshot: {
          title: item.title,
          original_title: item.original_title,
          year: item.year,
          rating: item.rating,
          rating_count: item.rating_count,
          poster_path: item.poster_path,
          backdrop_path: item.backdrop_path
        }
      })
    }),
  removeExternalFavorite: (mediaType: "movie" | "tv", providerId: number) =>
    request<void>("/discovery/favorites/" + mediaType + "/" + providerId, { method: "DELETE" }),
  addFavorite: (movieId: number, note = "") =>
    request<Favorite>(`/favorites/${movieId}`, {
      method: "PUT",
      body: JSON.stringify({ note })
    }),
  removeFavorite: (movieId: number) =>
    request<void>(`/favorites/${movieId}`, { method: "DELETE" })
};
