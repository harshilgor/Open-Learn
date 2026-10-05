'use client';

import { useId, useState, type FormEvent } from 'react';
import { LearningApiError } from '@/lib/api';
import { searchClassYoutubeVideos, type ClassYoutubeVideo } from '@/lib/class-youtube';
import styles from './class-youtube-search.module.css';

type Props = { classId: string };

export function ClassYoutubeSearch({ classId }: Props) {
  const id = useId();
  const [query, setQuery] = useState('');
  const [videos, setVideos] = useState<ClassYoutubeVideo[]>([]);
  const [selected, setSelected] = useState<ClassYoutubeVideo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = query.trim();
    if (value.length < 2 || busy) return;
    setBusy(true);
    setError('');
    setSelected(null);
    try {
      setVideos(await searchClassYoutubeVideos(classId, value));
    } catch (cause) {
      setVideos([]);
      setError(cause instanceof LearningApiError && cause.code === 'youtube_search_unavailable'
        ? 'YouTube search is not configured for this Open Learn instance.'
        : cause instanceof Error ? cause.message : 'YouTube search failed. Try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.panel} aria-labelledby={`${id}-heading`}>
      <h3 id={`${id}-heading`}>YouTube videos</h3>
      <p>Search YouTube for a supporting video, then choose one to play here.</p>
      <form className={styles.search} onSubmit={search}>
        <label htmlFor={`${id}-query`}>Search YouTube</label>
        <div className={styles.searchRow}>
          <input
            id={`${id}-query`}
            type="search"
            value={query}
            maxLength={160}
            minLength={2}
            onChange={event => setQuery(event.target.value)}
            placeholder="e.g. mitosis explained"
          />
          <button type="submit" disabled={busy || query.trim().length < 2}>
            {busy ? 'Searching…' : 'Search'}
          </button>
        </div>
      </form>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {videos.length ? (
        <ul className={styles.results} aria-label="YouTube search results">
          {videos.map(video => (
            <li key={video.videoId}>
              <button type="button" onClick={() => setSelected(video)} aria-pressed={selected?.videoId === video.videoId}>
                {/* YouTube requires its returned thumbnail to remain visible and unmodified. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={video.thumbnail.url} alt="" width={video.thumbnail.width ?? undefined} height={video.thumbnail.height ?? undefined} />
                <span>{video.title}</span>
                <small>{video.channelTitle}</small>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {videos.length === 0 && !busy && !error ? <p className={styles.empty}>Search YouTube to find videos for this class.</p> : null}
      {selected ? (
        <div className={styles.player}>
          <h4>{selected.title}</h4>
          <p>{selected.channelTitle}</p>
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${encodeURIComponent(selected.videoId)}`}
            title={`YouTube video: ${selected.title}`}
            referrerPolicy="strict-origin-when-cross-origin"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            allowFullScreen
          />
        </div>
      ) : null}
    </section>
  );
}
