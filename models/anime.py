from pydantic import BaseModel


class AnimeCard(BaseModel):
    mal_id: int | None = None
    shikimori_id: int | None = None

    title_ru: str | None = None
    title_en: str | None = None
    title_jp: str | None = None

    score: float | None = None
    episodes: int | None = None
    status: str | None = None
    genres: list[str] = []
    year: int | None = None

    synopsis_ru: str | None = None
    synopsis_en: str | None = None

    image_url: str | None = None
    mal_url: str | None = None
    anilibria_url: str | None = None
    anilibria_code: str | None = None
    episodes_available: list[int] = []
    episode_uuids: dict[int, str] = {}  # ordinal → episode uuid (for direct player URLs)
    torrents: list[dict] = []  # each: {id, quality, size_gb, seeders, episodes}
    yummy_url: str | None = None
    crunchyroll_url: str | None = None
    kodik_url: str | None = None
    kodik_episodes: dict[int, str] = {}  # {ep_num: full player URL}
    kodik_last_ep: int | None = None
    kodik_translation: str | None = None

    def primary_title(self, lang: str) -> str:
        if lang == "ru" and self.title_ru:
            return self.title_ru
        return self.title_en or self.title_ru or self.title_jp or "—"

    def synopsis(self, lang: str) -> str:
        if lang == "ru" and self.synopsis_ru:
            return self.synopsis_ru
        return self.synopsis_en or self.synopsis_ru or ""

    def watch_url(self, lang: str) -> str | None:
        return self.anilibria_url

    def _search_query(self, prefer_ru: bool) -> str:
        if prefer_ru:
            return self.title_ru or self.title_en or self.title_jp or ""
        return self.title_en or self.title_ru or self.title_jp or ""

    def yummy_search_url(self) -> str:
        if self.yummy_url:
            return self.yummy_url
        from urllib.parse import quote_plus
        return f"https://yummyanime.tv/index.php?do=search&subaction=search&story={quote_plus(self._search_query(prefer_ru=True))}"
