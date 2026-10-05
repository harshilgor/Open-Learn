import { request } from './api';

export type ClassYoutubeVideo = {
  videoId: string;
  title: string;
  channelTitle: string;
  publishedAt: string | null;
  thumbnail: { url: string; width: number | null; height: number | null };
};

export async function searchClassYoutubeVideos(
  classId: string,
  query: string,
  signal?: AbortSignal,
): Promise<ClassYoutubeVideo[]> {
  const params = new URLSearchParams({ q: query, maxResults: '8' });
  const response = await request<{ items: ClassYoutubeVideo[] }>(
    `/v1/class-sessions/${encodeURIComponent(classId)}/youtube/search?${params}`,
    { signal },
  );
  return response.items;
}
