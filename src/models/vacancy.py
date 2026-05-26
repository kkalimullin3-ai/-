# Единая модель вакансии для всех источников (hh, telegram)
# Поля заполняются в два этапа:
#   1) Парсеры (HhParser, TgParser) — заполняют идентификацию,
#      описание и метаданные. Зарплату — только для hh (в tg она в тексте).
#   2) Процессоры (SalaryNormalizer, SkillExtractor, GradeDetector,
#      RoleClassifier) — обогащают вакансию: вытаскивают зарплату из текста,
#      выделяют навыки, определяют грейд и каноническую роль.

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Vacancy:
    # Идентификация
    source: str                          # "hh" или "telegram" — откуда вакансия
    source_id: str                       # уникальный id в рамках источника
                                         # (для hh — id вакансии, для tg — id сообщения)

    title: str                           # название должности ("Аналитик данных")
    employer: Optional[str] = None       # название работодателя (для tg может быть None)
    city: Optional[str] = None           # город / локация
    url: Optional[str] = None            # ссылка на вакансию

    # Зарплата (для hh приходит из API, для tg — вытащит SalaryNormalizer из текста)
    salary_from: Optional[int] = None
    salary_to: Optional[int] = None
    salary_currency: Optional[str] = None   # "RUR", "USD", "EUR", ...
    salary_gross: Optional[bool] = None     # True = до вычета налогов, False = на руки

    # Требования (из hh приходят, из tg остаются None — могут быть выделены процессорами)
    experience: Optional[str] = None        # "Нет опыта", "От 1 года до 3 лет", ...
    employment: Optional[str] = None        # "Полная занятость", "Частичная", ...
    schedule: Optional[str] = None          # "Удалённо", "Полный день", "Гибрид", ...
    # Навыки
    key_skills: list[str] = field(default_factory=list)  # структурированные теги от hh
    skills: list[str] = field(default_factory=list)  # навыки в КАНОНИЧЕСКОЙ форме (для аналитики)
    skills_raw: list[str] = field(default_factory=list)  # навыки СЫРОЙ формы из секций "Стек:", "Требования:"
    # для расширения словаря

    # Текст и контекст
    description: Optional[str] = None       # полный текст описания вакансии
    search_query: Optional[str] = None      # для hh — поисковая фраза, для tg — имя канала
    search_position: Optional[int] = None   # порядковый номер в результатах поиска

    # Поля, добавляемые процессорами (по умолчанию None)
    grade: Optional[str] = None             # "junior" / "middle" / "senior" / "lead"
    role_canonical: Optional[str] = None    # "product_analyst", "data_engineer", "ml_engineer", ...

    # Метаданные
    published_at: Optional[datetime] = None              # когда опубликована
    parsed_at: datetime = field(default_factory=datetime.now)  # когда мы её спарсили

    # Исходный объект из API / сырой текст — на всякий случай
    raw: Optional[dict] = None

    @property
    def all_skills(self) -> list[str]:
        # Объединённый список навыков из обоих источников без дублей.
        seen = set()
        result = []
        for skill in self.key_skills + self.skills:
            key = skill.lower().strip()
            if key and key not in seen:
                seen.add(key)
                result.append(skill)
        return result

    def to_dict(self) -> dict:
        # Конвертация в обычный dict — для сохранения в JSON / pandas DataFrame.
        data = asdict(self)
        if self.published_at is not None:
            data["published_at"] = self.published_at.isoformat()
        data["parsed_at"] = self.parsed_at.isoformat()
        return data

    def __str__(self) -> str:
        # Короткое читаемое представление — удобно для логов и отладки.
        salary = self._format_salary()
        return f"[{self.source}] {self.title} @ {self.employer or '?'} ({salary})"

    def _format_salary(self) -> str:
        # Вспомогательный метод для красивого вывода зп.
        if self.salary_from is None and self.salary_to is None:
            return "ЗП не указана"
        parts = []
        if self.salary_from is not None:
            parts.append(f"от {self.salary_from:,}".replace(",", " "))
        if self.salary_to is not None:
            parts.append(f"до {self.salary_to:,}".replace(",", " "))
        currency = self.salary_currency or ""
        return " ".join(parts) + f" {currency}".rstrip()