#храним просто все вакансии и с хх и с всевозможных тгк

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Vacancy:


    # Идентификация
    source: str                       # "hh" или "telegram" — откуда вакансия
    source_id: str                    # уникальный id в рамках источника
                                      # (для hh - id вакансии, для tg — id сообщения)

    title: str                        # название должности ("Аналитик данных")
    employer: Optional[str] = None    # название работодателя (для tg может быть None)
    city: Optional[str] = None        # город / локация
    url: Optional[str] = None         # ссылка на вакансию

    # Зарплата
    salary_from: Optional[int] = None      
    salary_to: Optional[int] = None       
    salary_currency: Optional[str] = None   # "RUR", "USD", "EUR", ...
    salary_gross: Optional[bool] = None     # True = до вычета налогов, False = на руки

    # Требования
    experience: Optional[str] = None        # "Нет опыта", "От 1 года до 3 лет", ...
    employment: Optional[str] = None        # "Полная занятость", "Частичная", ...
    schedule: Optional[str] = None          # "Удалённо", "Полный день", "Гибрид", ...



    key_skills: list[str] = field(default_factory=list) # теги в хх

    skills: list[str] = field(default_factory=list) # навыки из описания


    description: Optional[str] = None       # полный текст описания вакансии
    search_query: Optional[str] = None      # для конкретных похициций "аналитик данных", "product analyst", ...
    search_position: Optional[int] = None   # порядковый номер в результатах поиска (1-й, 2-й, ...; на странице hh 20 штук)
  
    #Метаданные
    published_at: Optional[datetime] = None     # когда опубликована
    parsed_at: datetime = field(default_factory=datetime.now) # когда мы ее спарсили 


 
    raw: Optional[dict] = None # На всякий случай сохраняем исходный объект из API/сырой текст 
    
  
    @property
    def all_skills(self) -> list[str]:
        #Объединённый список навыков из обоих источников без дублей.
        seen = set()
        result = []
        for skill in self.key_skills + self.skills:
            key = skill.lower().strip()
            if key and key not in seen:
                seen.add(key)
                result.append(skill)
        return result
      
    def to_dict(self) -> dict:
        #Конвертация в обычный dict — для сохранения в JSON / pandas DataFrame.

        data = asdict(self)
        if self.published_at is not None:
            data["published_at"] = self.published_at.isoformat()
        data["parsed_at"] = self.parsed_at.isoformat()
        return data

    def __str__(self) -> str:
        #Короткое читаемое представление — удобно для логов и отладки.

        salary = self._format_salary()
        return f"[{self.source}] {self.title} @ {self.employer or '?'} ({salary})"

    def _format_salary(self) -> str:
        #Вспомогательный метод для красивого вывода зп 
        if self.salary_from is None and self.salary_to is None:
            return "ЗП не указана"
        parts = []
        if self.salary_from is not None:
            parts.append(f"от {self.salary_from:,}".replace(",", " "))
        if self.salary_to is not None:
            parts.append(f"до {self.salary_to:,}".replace(",", " "))
        currency = self.salary_currency or ""
        return " ".join(parts) + f" {currency}".rstrip()
