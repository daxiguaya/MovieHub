import type {
  Chart,
  ChartMoviesResponse,
  ChartCompareResponse,
  ChartSnapshot,
  Favorite,
  MovieDetail,
  MoviesResponse
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
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
  addFavorite: (movieId: number, note = "") =>
    request<Favorite>(`/favorites/${movieId}`, {
      method: "PUT",
      body: JSON.stringify({ note })
    }),
  removeFavorite: (movieId: number) =>
    request<void>(`/favorites/${movieId}`, { method: "DELETE" })
};
