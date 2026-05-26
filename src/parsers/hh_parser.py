# Парсер вакансий с hh.ru через официальный Open API.
# Документация API: https://api.hh.ru/openapi/redoc
#
# Алгоритм работы:
#   1. Для каждого поискового запроса (например, "аналитик данных") идём
#      постранично в /vacancies и забираем id вакансий.
#   2. Для каждого id делаем второй запрос /vacancies/{id} — потому что
#      в списке нет description и key_skills, они есть только в детальной карточке.
#   3. Конвертируем JSON в объект Vacancy и складываем в общий список.
#   4. Дедуплицируем по source_id — одна вакансия может найтись по нескольким запросам.

import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from src.models.vacancy import Vacancy
from src.parsers.base import BaseParser


class HhParser(BaseParser):
    source_name = "hh"
    API_BASE = "https://api.hh.ru"
    USER_AGENT = "TechLn-Research/1.0 (kkalimullin3@gmail.com)"
    REQUEST_DELAY = 0.25
    MAX_RETRIES = 3

    def __init__(
        self,
        search_queries: list[str],
        area_id: int = 113,
        max_pages: int = 20,
        per_page: int = 100,
        output_dir: str = "data/raw",
    ):
        super().__init__(output_dir=output_dir)

        self.search_queries = search_queries
        self.area_id = area_id
        self.max_pages = max_pages
        self.per_page = per_page

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.USER_AGENT})

    def collect(self) -> list[Vacancy]:
        all_vacancies: list[Vacancy] = []
        seen_ids: set[str] = set()

        for query in tqdm(self.search_queries, desc="Запросы"):
            self.logger.info(f"Поиск по запросу: '{query}'")
            position = 0

            for page in range(self.max_pages):
                items = self._search_page(query, page)

                if not items:
                    self.logger.info(f"  Страница {page} пустая, прекращаем")
                    break

                for item in tqdm(items, desc=f"  стр {page}", leave=False):
                    position += 1
                    vacancy_id = item["id"]

                    if vacancy_id in seen_ids:
                        continue
                    seen_ids.add(vacancy_id)

                    detail = self._fetch_vacancy_detail(vacancy_id)
                    if detail is None:
                        continue

                    if detail.get("archived"):
                        continue

                    vacancy = self._to_vacancy(detail, query, position)
                    all_vacancies.append(vacancy)

        return all_vacancies

    def _search_page(self, query: str, page: int) -> list[dict]:
        params = {
            "text": query,
            "area": self.area_id,
            "page": page,
            "per_page": self.per_page,
            "search_field": "name",
        }
        response = self._request(f"{self.API_BASE}/vacancies", params=params)
        if response is None:
            return []
        return response.get("items", [])

    def _fetch_vacancy_detail(self, vacancy_id: str) -> Optional[dict]:
        url = f"{self.API_BASE}/vacancies/{vacancy_id}"
        return self._request(url)

    def _request(self, url: str, params: Optional[dict] = None) -> Optional[dict]:
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                time.sleep(self.REQUEST_DELAY)
                response = self.session.get(url, params=params, timeout=10)

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 404:
                    self.logger.warning(f"404 для {url} — вакансия удалена")
                    return None

                if response.status_code >= 500:
                    wait = 2 ** (attempt - 1)
                    self.logger.warning(
                        f"{response.status_code} от hh, попытка {attempt}/{self.MAX_RETRIES}, пауза {wait}с"
                    )
                    time.sleep(wait)
                    continue

                self.logger.error(f"{response.status_code} от {url}: {response.text[:200]}")
                return None

            except requests.exceptions.RequestException as e:
                wait = 2 ** (attempt - 1)
                self.logger.warning(f"Ошибка сети: {e}. Попытка {attempt}/{self.MAX_RETRIES}, пауза {wait}с")
                time.sleep(wait)

        self.logger.error(f"Все {self.MAX_RETRIES} попытки исчерпаны для {url}")
        return None

    def _to_vacancy(self, v: dict, search_query: str, position: int) -> Vacancy:
        salary = v.get("salary") or {}

        experience = (v.get("experience") or {}).get("name")
        employment = (v.get("employment") or {}).get("name")
        schedule = (v.get("schedule") or {}).get("name")

        employer = (v.get("employer") or {}).get("name")
        city = (v.get("area") or {}).get("name")

        key_skills = [s["name"] for s in (v.get("key_skills") or [])]

        description_raw = v.get("description") or ""
        description = self._clean_html(description_raw) if description_raw else None

        published_at = None
        published_raw = v.get("published_at")
        if published_raw:
            try:
                published_at = datetime.fromisoformat(published_raw)
            except ValueError:
                pass

        return Vacancy(
            source=self.source_name,
            source_id=str(v["id"]),
            title=v.get("name", ""),
            employer=employer,
            city=city,
            url=v.get("alternate_url"),
            salary_from=salary.get("from"),
            salary_to=salary.get("to"),
            salary_currency=salary.get("currency"),
            salary_gross=salary.get("gross"),
            experience=experience,
            employment=employment,
            schedule=schedule,
            key_skills=key_skills,
            skills=[],
            description=description,
            search_query=search_query,
            search_position=position,
            published_at=published_at,
            raw=v,
        )

    @staticmethod
    def _clean_html(html: str) -> str:
        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)