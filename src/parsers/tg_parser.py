"""
Парсер вакансий из Telegram-каналов через Telethon.

Что делает парсер по этапам:
1. Подключается к Telegram как обычный клиент (api_id/ из .env).
2. Идёт по списку каналов и забирает последние N сообщений из каждого.
3. Грубо отфильтровывает не-вакансии (по ключевым словам + длине)

"""

import os
import re

from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.tl.types import Message
from src.models.vacancy import Vacancy
from src.parsers.base import BaseParser


class TgParser(BaseParser):
    source_name = "telegram"

    # Ключевые слова для релевантной роли (аналитика + DS/ML).
    ROLE_KEYWORDS = [
        "аналитик", "analyst", "аналитика", "analytics",
        "bi-аналитик", "bi analyst", "bi engineer",
        "продуктовый аналитик", "product analyst",
        "бизнес-аналитик", "бизнес аналитик", "business analyst",
        "системный аналитик", "system analyst",
        "маркетинг-аналитик", "marketing analyst",
        "data analyst", "дата-аналитик", "дата аналитик",
        "data scientist", "data science",
        "ml engineer", "ml-engineer", "machine learning",
        "data engineer", "дата-инженер",
        "dwh", "etl", "хранилищ",
        "quant researcher", "quantitative",
    ]

    # Индикаторы того, что пост - это вакансия (а не анонс мероприятия).
    VACANCY_INDICATORS = [
        "вакансия", "vacancy", "ищем", "looking for", "we are hiring",
        "позиция", "position", "роль", "role",
        "responsibilities", "обязанности",
        "requirements", "требования",
        "зарплата", "salary", "вилка", "оклад",
        "формат работы", "удалён", "удален", "remote", "офис",
    ]

    MIN_TEXT_LENGTH = 300

    NOISE_PATTERNS = [
        re.compile(
            r"——\s*⚠️\s*Безопасность соискателя!.*?——",
            re.DOTALL | re.IGNORECASE,
        ),
        re.compile(
            r"⚠️\s*ВНИМАНИЮ ВСЕХ УЧАСТНИКОВ СООБЩЕСТВА.*?(?=\n\n[А-ЯA-Z]|\Z)",
            re.DOTALL,
        ),
        re.compile(
            r"🔗\s*Перед откликом.*?(?=\n\n|\Z)",
            re.DOTALL,
        ),
    ]

    def __init__(
            self,
            channels: list[str],
            messages_per_channel: int | None = 300,  # None = качать всё
            output_dir: str = "data/raw",
            apply_filters: bool = True,  # False = не фильтровать по ключевым словам
    ):
        super().__init__(output_dir=output_dir)
        self.channels = channels
        self.messages_per_channel = messages_per_channel
        self.apply_filters = apply_filters

        load_dotenv()
        self.api_id = int(os.getenv("TG_API_ID"))
        self.api_hash = os.getenv("TG_API_HASH")
        self.phone = os.getenv("TG_PHONE")

        if not all([self.api_id, self.api_hash, self.phone]):
            raise ValueError(
                "В .env должны быть заданы TG_API_ID, TG_API_HASH, TG_PHONE."
            )

        self.session_name = "techln"

    def collect(self) -> list[Vacancy]:
        # Возвращаем общий список (для обратной совместимости),
        # но дополнительно сохраняем КАЖДЫЙ канал в свой файл сразу как только обработали.
        all_vacancies: list[Vacancy] = []

        with TelegramClient(self.session_name, self.api_id, self.api_hash) as client:
            client.start(phone=self.phone)
            self.logger.info(f"Подключён к Telegram как {self.phone}")

            for channel in self.channels:
                # Проверка кэша: если файл этого канала уже есть -пропускаем.
                # Это позволяет дозагружать новые каналы, не перекачивая старые.
                channel_file = self._channel_file_path(channel)
                if channel_file.exists():
                    self.logger.info(
                        f"  {channel}: файл {channel_file.name} уже есть, пропускаем"
                    )
                    continue

                self.logger.info(f"Читаем канал {channel}...")
                channel_vacancies = self._collect_from_channel(client, channel)
                self.logger.info(
                    f"  из {channel}: {len(channel_vacancies)} вакансий (после фильтрации)"
                )

                # Сохраняем этот канал в свой файл прямо сейчас.
                self._save_channel(channel, channel_vacancies)

                all_vacancies.extend(channel_vacancies)

        return all_vacancies

    def _channel_file_path(self, channel: str):
        # Имя файла строится из имени канала без @.
        # Например, @datasciencejobs -> data/raw/telegram_datasciencejobs.json
        from pathlib import Path
        channel_clean = channel.lstrip("@")
        return Path(self.output_dir) / f"telegram_{channel_clean}.json"

    def _save_channel(self, channel: str, vacancies: list[Vacancy]) -> None:
        # Сохраняет список вакансий конкретного канала в свой JSON-файл.
        # Используется внутри collect() сразу после обработки канала, чтобы созранять файл сразу

        import json

        channel_file = self._channel_file_path(channel)
        channel_file.parent.mkdir(parents=True, exist_ok=True)

        data = [v.to_dict() for v in vacancies]
        with open(channel_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

        size_mb = channel_file.stat().st_size / (1024 * 1024)
        self.logger.info(
            f"  Сохранено {len(vacancies)} вакансий в {channel_file} ({size_mb:.1f} МБ)"
        )

    def _collect_from_channel(self, client: TelegramClient, channel: str) -> list[Vacancy]:
        vacancies: list[Vacancy] = []
        total_seen = 0
        total_filtered = 0

        # limit=None в iter_messages → качать всё до конца истории канала.
        for message in client.iter_messages(channel, limit=self.messages_per_channel):
            total_seen += 1

            # Прогресс-лог каждые 500 сообщений - чтобы видно было, что не все не зависло.
            if total_seen % 500 == 0:
                self.logger.info(
                    f"  ...прогресс {channel}: просмотрено {total_seen}, собрано {len(vacancies)}"
                )

            if not message.text:
                continue

            text = self._clean_noise(message.text)

            # Минимальная длина - оставляем всегда, чтобы отсекать совсем короткие посты
            # (картинки с подписью "ого", односложные комментарии и т.п.).
            if len(text) < self.MIN_TEXT_LENGTH:
                total_filtered += 1
                continue

            # Фильтры по содержимому применяем только если apply_filters=True.
            if self.apply_filters:
                if not self._is_vacancy(text):
                    total_filtered += 1
                    continue

                if not self._is_relevant_role(text):
                    total_filtered += 1
                    continue

            vacancies.append(self._to_vacancy(message, text, channel))

        self.logger.info(
            f"  Просмотрено: {total_seen}, отфильтровано: {total_filtered}, осталось: {len(vacancies)}"
        )
        return vacancies

    def _clean_noise(self, text: str) -> str:
        for pattern in self.NOISE_PATTERNS:
            text = pattern.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _is_vacancy(self, text: str) -> bool:
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in self.VACANCY_INDICATORS)

    def _is_relevant_role(self, text: str) -> bool:
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.ROLE_KEYWORDS)

    def _to_vacancy(self, message: Message, cleaned_text: str, channel: str) -> Vacancy:
        title = self._extract_first_line(cleaned_text)
        channel_clean = channel.lstrip("@")
        url = f"https://t.me/{channel_clean}/{message.id}"

        return Vacancy(
            source=self.source_name,
            source_id=f"{channel_clean}_{message.id}",
            title=title,
            employer=None,
            city=None,
            url=url,
            salary_from=None,
            salary_to=None,
            salary_currency=None,
            salary_gross=None,
            experience=None,
            employment=None,
            schedule=None,
            key_skills=[],
            skills=[],
            description=cleaned_text,
            search_query=channel,
            search_position=None,
            published_at=message.date,
            raw={
                "message_id": message.id,
                "channel": channel,
                "original_text": message.text,
            },
        )

    @staticmethod
    def _extract_first_line(text: str) -> str:
        for line in text.split("\n"):
            line = line.strip()
            if line and len(line) > 5:
                return line[:200]
        return "(без заголовка)"
