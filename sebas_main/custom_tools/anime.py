"""Anime life, via AniList's public GraphQL API.

- anime_airing: what airs today or in the next few days (in local time), from
  your watching/planning list, or the season's most popular shows.
- anime_list: what you are watching, planning, have completed or paused.
- anime_progress: "I finished episode 7 of Frieren" updates your AniList entry.
- release_radar: new chapters/volumes for the manga and light novels you
  follow, and new episodes of the anime, since the last check.
- anime_suggest: recommendations from what you rated highly, filtered by
  genre, length or format.

ANILIST_TOKEN (from a one-time sign-in, see README) lets Sebas read your
private list and update it; without it, ANILIST_USER gives read-only access to
a public list, and with neither only the public schedule is available.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

import httpx
from openjarvis.core.paths import get_data_dir
from openjarvis.core.registry import ToolRegistry

from custom_tools._base import SebasTool, ToolError

API = "https://graphql.anilist.co"
_viewer_cache: dict[str, Any] = {}


def _token() -> str:
    return os.environ.get("ANILIST_TOKEN", "").strip()


def gql(query: str, variables: dict | None = None, *, auth: bool = True) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth and _token():
        headers["Authorization"] = f"Bearer {_token()}"
    for attempt in range(2):
        try:
            response = httpx.post(API, json={"query": query, "variables": variables or {}}, headers=headers, timeout=20)
        except httpx.HTTPError as exc:
            raise ToolError(f"Could not reach AniList: {exc}") from exc
        if response.status_code == 429 and attempt == 0:  # AniList rate limit: wait as told, once
            time.sleep(min(int(response.headers.get("Retry-After", "5")), 30))
            continue
        break
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code in (400, 401) and "Invalid token" in json.dumps(data):
        raise ToolError("AniList rejected the token; it may have expired (they last a year). Please sign in again.")
    if data.get("errors"):
        raise ToolError("AniList: " + "; ".join(e.get("message", "?") for e in data["errors"])[:300])
    if response.status_code >= 400:
        raise ToolError(f"AniList returned HTTP {response.status_code}.")
    return data["data"]


def viewer() -> dict | None:
    """{'id', 'name'} of the signed-in or configured user, or None."""
    if _token():
        if "auth" not in _viewer_cache:
            _viewer_cache["auth"] = gql("query { Viewer { id name } }")["Viewer"]
        return _viewer_cache["auth"]
    name = os.environ.get("ANILIST_USER", "").strip()
    if name:
        if name not in _viewer_cache:
            _viewer_cache[name] = gql("query($n:String){ User(name:$n){ id name } }", {"n": name}, auth=False)["User"]
        return _viewer_cache[name]
    return None


def _title(media: dict) -> str:
    t = media.get("title") or {}
    return t.get("english") or t.get("romaji") or t.get("native") or "?"


_LIST_QUERY = """
query($uid:Int, $type:MediaType) {
  MediaListCollection(userId:$uid, type:$type) {
    lists { status entries {
      id status progress progressVolumes score(format:POINT_10)
      media { id format status episodes chapters volumes averageScore genres
              title { english romaji native }
              nextAiringEpisode { episode airingAt } }
    } }
  }
}"""


def list_entries(kind: str = "ANIME") -> list[dict]:
    user = viewer()
    if user is None:
        raise ToolError("Set ANILIST_TOKEN (or ANILIST_USER) in .env so I can see your list.")
    data = gql(_LIST_QUERY, {"uid": user["id"], "type": kind})
    return [e for lst in data["MediaListCollection"]["lists"] for e in lst["entries"]]


def _when(epoch: int) -> str:
    dt = datetime.fromtimestamp(epoch)
    day = "today" if dt.date() == datetime.now().date() else "tomorrow" if dt.date() == datetime.now().date() + timedelta(days=1) else dt.strftime("%A")
    return f"{day} {dt.strftime('%I:%M %p').lstrip('0')}"


@ToolRegistry.register("anime_airing")
class AnimeAiringTool(SebasTool):
    name = "anime_airing"
    description = (
        "What anime episodes air today (or within the next few days), in local time. "
        "Covers the user's watching and planning list when AniList is connected; "
        "otherwise, or with popular=true, the season's most popular shows."
    )
    parameters = {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "How many days ahead, 1 = today only (max 7)."},
            "popular": {"type": "boolean", "description": "true for popular shows instead of the user's list."},
        },
    }

    def run(self, days: int = 1, popular: bool = False) -> str:
        days = max(1, min(int(days or 1), 7))
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=days)
        mine = None
        if not popular and viewer() is not None:
            mine = {e["media"]["id"] for e in list_entries() if e["status"] in ("CURRENT", "PLANNING", "REPEATING")}
        rows, page = [], 1
        while page <= 4:
            data = gql("""query($a:Int,$b:Int,$p:Int){ Page(page:$p, perPage:50){ pageInfo{ hasNextPage }
                airingSchedules(airingAt_greater:$a, airingAt_lesser:$b, sort:TIME){ episode airingAt
                media{ id popularity isAdult title{ english romaji } } } } }""",
                       {"a": int(start.timestamp()), "b": int(end.timestamp()), "p": page}, auth=False)["Page"]
            rows += [s for s in data["airingSchedules"] if not s["media"]["isAdult"]]
            if not data["pageInfo"]["hasNextPage"]:
                break
            page += 1
        if mine is not None:
            rows = [s for s in rows if s["media"]["id"] in mine]
            if not rows:
                return "Nothing on your watching or planning list airs " + ("today." if days == 1 else f"in the next {days} days.")
        else:
            rows = sorted(rows, key=lambda s: -(s["media"]["popularity"] or 0))[:12]
            rows.sort(key=lambda s: s["airingAt"])
        source = "From your list" if mine is not None else "Popular this season"
        now = time.time()
        lines = [f"- {_when(s['airingAt'])}: {_title(s['media'])} episode {s['episode']}"
                 + (" (aired)" if s["airingAt"] < now else "") for s in rows]
        return f"{source}:\n" + "\n".join(lines)


@ToolRegistry.register("anime_list")
class AnimeListTool(SebasTool):
    name = "anime_list"
    description = "The user's AniList anime or manga/light-novel list: watching/reading, planning, completed, paused or dropped."
    parameters = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["CURRENT", "PLANNING", "COMPLETED", "PAUSED", "DROPPED"]},
            "kind": {"type": "string", "enum": ["ANIME", "MANGA"], "description": "MANGA includes light novels."},
        },
        "required": ["status"],
    }

    def run(self, status: str, kind: str = "ANIME") -> str:
        entries = [e for e in list_entries(kind) if e["status"] == status]
        if not entries:
            return f"Nothing is {status.lower()} on your {kind.lower()} list."
        unit = "ep" if kind == "ANIME" else "ch"
        total_key = "episodes" if kind == "ANIME" else "chapters"
        lines = []
        for e in sorted(entries, key=lambda e: _title(e["media"]))[:40]:
            m = e["media"]; total = m.get(total_key)
            extra = f" ({m['format'].replace('_', ' ').lower()})" if kind == "MANGA" and m.get("format") == "NOVEL" else ""
            nxt = m.get("nextAiringEpisode")
            airing = f", ep {nxt['episode']} {_when(nxt['airingAt'])}" if nxt else ""
            score = f", rated {e['score']:g}/10" if e.get("score") else ""
            lines.append(f"- {_title(m)}{extra}: {unit} {e['progress']}{'/' + str(total) if total else ''}{score}{airing}")
        more = f"\n(and {len(entries) - 40} more)" if len(entries) > 40 else ""
        return f"{len(entries)} {status.lower()}:\n" + "\n".join(lines) + more


def _find(entries: list[dict], title: str) -> dict:
    target = title.strip().lower()

    def score(e: dict) -> float:
        names = [n for n in (e["media"]["title"] or {}).values() if n]
        return max((SequenceMatcher(None, target, n.lower()).ratio() + (0.4 if target in n.lower() else 0)) for n in names)

    ranked = sorted(entries, key=score, reverse=True)
    if not ranked or score(ranked[0]) < 0.55:
        raise ToolError(f"'{title}' is not on your list.")
    return ranked[0]


@ToolRegistry.register("anime_progress")
class AnimeProgressTool(SebasTool):
    name = "anime_progress"
    description = (
        "Update the user's AniList progress: the episode (or chapter) they reached, and "
        "optionally a score out of 10 or a new status. 'I finished episode 7 of Frieren' -> progress 7."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "progress": {"type": "integer", "description": "Episode or chapter number reached."},
            "score": {"type": "number", "description": "Score out of 10, if the user gave one."},
            "status": {"type": "string", "enum": ["CURRENT", "PLANNING", "COMPLETED", "PAUSED", "DROPPED"]},
            "kind": {"type": "string", "enum": ["ANIME", "MANGA"]},
        },
        "required": ["title"],
    }

    def run(self, title: str, progress: int | None = None, score: float | None = None,
            status: str | None = None, kind: str = "ANIME") -> str:
        if not _token():
            raise ToolError("Updating AniList needs ANILIST_TOKEN (a one-time sign-in, see README).")
        entry = _find(list_entries(kind), title)
        media = entry["media"]
        total = media.get("episodes" if kind == "ANIME" else "chapters")
        variables: dict[str, Any] = {"id": media["id"]}
        if progress is not None:
            variables["progress"] = int(progress)
            if total and int(progress) >= total and status is None:
                status = "COMPLETED"
            elif status is None and entry["status"] == "PLANNING":
                status = "CURRENT"
        if score is not None:
            variables["score"] = max(0.0, min(float(score), 10.0))
        if status:
            variables["status"] = status
        if len(variables) == 1:
            raise ToolError("Say the episode reached, a score, or a status.")
        saved = gql("""mutation($id:Int,$progress:Int,$score:Float,$status:MediaListStatus){
            SaveMediaListEntry(mediaId:$id, progress:$progress, score:$score, status:$status){ progress status score(format:POINT_10) } }""",
                    variables)["SaveMediaListEntry"]
        unit = "episode" if kind == "ANIME" else "chapter"
        text = f"{_title(media)}: {unit} {saved['progress']}{'/' + str(total) if total else ''}, {saved['status'].lower()}"
        return text + (f", rated {saved['score']:g}/10." if saved.get("score") else ".")


def _radar_path():
    return get_data_dir() / "sebas" / "anime_radar.json"


def radar_changes() -> list[str]:
    """What is new since the last check: episodes aired, chapters and volumes added."""
    path = _radar_path()
    try:
        seen = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        seen = {}
    first = not seen
    news, now = [], {}
    for kind in ("ANIME", "MANGA"):
        for e in list_entries(kind):
            if e["status"] not in ("CURRENT", "PLANNING", "PAUSED", "REPEATING"):
                continue
            m = e["media"]; key = f"{kind}:{m['id']}"
            if kind == "ANIME":
                nxt = m.get("nextAiringEpisode")
                aired = (nxt["episode"] - 1) if nxt else (m.get("episodes") or 0)
                now[key] = {"aired": aired}
                old = seen.get(key, {}).get("aired")
                if old is not None and aired > old and e["status"] in ("CURRENT", "REPEATING"):
                    news.append(f"{_title(m)}: episode {aired} is out")
            else:
                now[key] = {"chapters": m.get("chapters"), "volumes": m.get("volumes")}
                old = seen.get(key, {})
                label = "light novel" if m.get("format") == "NOVEL" else "manga"
                if old.get("volumes") is not None and (m.get("volumes") or 0) > old["volumes"]:
                    news.append(f"{_title(m)} ({label}): volume {m['volumes']} is listed")
                elif old.get("chapters") is not None and (m.get("chapters") or 0) > old["chapters"]:
                    news.append(f"{_title(m)} ({label}): now {m['chapters']} chapters")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(now, indent=1), "utf-8")
    return ["(first check: your list has been noted; new releases will be reported from now on)"] if first else news


@ToolRegistry.register("release_radar")
class ReleaseRadarTool(SebasTool):
    name = "release_radar"
    description = (
        "What is new for the anime, manga and light novels on the user's AniList since the "
        "last check: new episodes aired, new chapters or volumes listed."
    )
    timeout_seconds = 60.0

    def run(self) -> str:
        news = radar_changes()
        return "\n".join(f"- {n}" for n in news) if news else "Nothing new since the last check."


@ToolRegistry.register("anime_suggest")
class AnimeSuggestTool(SebasTool):
    name = "anime_suggest"
    description = (
        "Suggest anime (or manga) the user has not seen, based on what they rated highly on "
        "AniList (or popular titles if not connected). Filter by genre (e.g. Comedy, "
        "Slice of Life, Romance, Action, Mystery), a maximum episode count for something "
        "short, and format (TV, MOVIE, OVA, NOVEL). Pick from the results to suit the user's mood."
    )
    parameters = {
        "type": "object",
        "properties": {
            "genre": {"type": "string"},
            "max_episodes": {"type": "integer"},
            "format": {"type": "string", "enum": ["TV", "MOVIE", "OVA", "ONA", "TV_SHORT", "MANGA", "NOVEL"]},
            "kind": {"type": "string", "enum": ["ANIME", "MANGA"]},
        },
    }
    timeout_seconds = 60.0

    def run(self, genre: str = "", max_episodes: int | None = None, format: str = "", kind: str = "ANIME") -> str:
        known: set[int] = set()
        favourites: list[int] = []
        if viewer() is not None:
            entries = list_entries(kind)
            known = {e["media"]["id"] for e in entries}
            rated = sorted((e for e in entries if e.get("score")), key=lambda e: -e["score"])
            favourites = [e["media"]["id"] for e in rated[:8]] or [e["media"]["id"] for e in entries if e["status"] == "COMPLETED"][:8]
        candidates: dict[int, dict] = {}
        if favourites:
            data = gql("""query($ids:[Int]){ Page(perPage:8){ media(id_in:$ids){ title{english romaji}
                recommendations(sort:RATING_DESC, perPage:10){ nodes{ rating mediaRecommendation{ id type format episodes chapters
                averageScore genres isAdult title{english romaji} } } } } } }""", {"ids": favourites})
            for source in data["Page"]["media"]:
                for node in source["recommendations"]["nodes"]:
                    m = node.get("mediaRecommendation")
                    if not m or m["isAdult"] or m["id"] in known or m["type"] != kind:
                        continue
                    c = candidates.setdefault(m["id"], {**m, "because": set(), "votes": 0})
                    c["because"].add(_title(source)); c["votes"] += max(node.get("rating") or 0, 0)
        if not candidates:  # not connected, or nothing to go on: the best-rated popular titles
            data = gql("""query($t:MediaType,$g:String){ Page(perPage:30){ media(type:$t, genre:$g, sort:SCORE_DESC,
                popularity_greater:20000, isAdult:false){ id format episodes chapters averageScore genres title{english romaji} } } }""",
                       {"t": kind, "g": genre or None}, auth=False)
            candidates = {m["id"]: {**m, "because": set(), "votes": 0} for m in data["Page"]["media"] if m["id"] not in known}
        picks = []
        for c in sorted(candidates.values(), key=lambda c: (-c["votes"], -(c.get("averageScore") or 0))):
            if genre and genre.lower() not in [g.lower() for g in c.get("genres") or []]:
                continue
            if max_episodes and (c.get("episodes") or 999) > max_episodes:
                continue
            if format and c.get("format") != format:
                continue
            length = f"{c['episodes']} eps" if c.get("episodes") else f"{c['chapters']} ch" if c.get("chapters") else (c.get("format") or "").lower()
            why = f"; because you liked {', '.join(sorted(c['because'])[:2])}" if c["because"] else ""
            picks.append(f"- {_title(c)} ({(c.get('format') or '').replace('_', ' ')}, {length}, "
                         f"score {c.get('averageScore') or '?'}%, {', '.join((c.get('genres') or [])[:3])}){why}")
            if len(picks) == 6:
                break
        return "\n".join(picks) if picks else "Nothing suitable turned up with those filters; try a broader genre or length."
