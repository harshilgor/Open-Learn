"""Explicit, read-only YouTube video search for an owned class session."""
import os
import re
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text

from .material_routes import material_owner

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def build_class_youtube_router(store_provider):
    router = APIRouter(prefix="/v1/class-sessions", tags=["class-youtube"])

    @router.get("/{identifier}/youtube/search")
    def search_videos(
        identifier: str,
        response: Response,
        q: str = Query(min_length=2, max_length=160),
        max_results: int = Query(5, alias="maxResults", ge=1, le=8),
        owner=Depends(material_owner),
        store=Depends(store_provider),
    ):
        response.headers["Cache-Control"] = "private, no-store"
        query = q.strip()
        if len(query) < 2:
            raise HTTPException(422, {"code": "invalid_search_query", "message": "Enter at least two characters to search YouTube."})

        # Verify ownership before spending external API quota. The API key is
        # kept on the server and is never included in the response or browser.
        with store.engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM class_sessions WHERE id=:id AND owner_id=:owner"),
                {"id": identifier, "owner": owner},
            ).first()
        if not exists:
            raise HTTPException(404, {"code": "class_not_found", "message": "Class session unavailable."})

        api_key = os.getenv("YOUTUBE_DATA_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(503, {"code": "youtube_search_unavailable", "message": "YouTube search is not configured."})

        params = {
            "key": api_key,
            "part": "snippet",
            "type": "video",
            "videoEmbeddable": "true",
            "safeSearch": "moderate",
            "maxResults": max_results,
            "q": query,
        }
        try:
            with httpx.Client(
                timeout=httpx.Timeout(6.0, connect=2.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                upstream = client.get(YOUTUBE_SEARCH_URL, params=params)
            upstream.raise_for_status()
            payload = upstream.json()
            raw_items = payload.get("items", []) if isinstance(payload, dict) else []
        except (httpx.HTTPError, ValueError, TypeError):
            raise HTTPException(502, {"code": "youtube_search_failed", "message": "YouTube search could not be completed. Try again shortly."}) from None

        items = []
        for item in raw_items[:max_results] if isinstance(raw_items, list) else []:
            if not isinstance(item, dict):
                continue
            video_id = (item.get("id") or {}).get("videoId") if isinstance(item.get("id"), dict) else None
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
                continue
            title = snippet.get("title")
            channel_title = snippet.get("channelTitle")
            if not isinstance(title, str) or not isinstance(channel_title, str):
                continue
            thumbnails = snippet.get("thumbnails") if isinstance(snippet.get("thumbnails"), dict) else {}
            thumbnail = thumbnails.get("medium") or thumbnails.get("default")
            thumbnail_url = thumbnail.get("url") if isinstance(thumbnail, dict) else None
            if not isinstance(thumbnail_url, str):
                continue
            parsed_thumbnail_url = urlsplit(thumbnail_url)
            if parsed_thumbnail_url.scheme != "https" or parsed_thumbnail_url.hostname not in {"i.ytimg.com", "img.youtube.com"}:
                continue
            items.append({
                "videoId": video_id,
                "title": title,
                "channelTitle": channel_title,
                "publishedAt": snippet.get("publishedAt") if isinstance(snippet.get("publishedAt"), str) else None,
                "thumbnail": {
                    "url": thumbnail_url,
                    "width": thumbnail.get("width") if isinstance(thumbnail.get("width"), int) else None,
                    "height": thumbnail.get("height") if isinstance(thumbnail.get("height"), int) else None,
                },
            })
        return {"items": items}

    return router
