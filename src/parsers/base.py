# Базовый класс для двух парсеров, который задаёт общий стиль за счет абстрактного класса


import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

# Импорт модели вакансии из класса Vacancy
from src.models.vacancy import Vacancy


class BaseParser(ABC):
# создаем обстрактный класс, чтобы наши парсеры обязательно определии методы в  @abstractmethod, иначе код не запустится 


    source_name: str = "base"

    def __init__(self, output_dir: str = "data/raw"):
        # output_dir — куда сохранять сырые данные
        self.output_dir = Path(output_dir)
        # mkdir с parents=True создаст всю цепочку папок, если их нет
        # exist_ok=True — код не упадет, если папка уже существует
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Логгер с именем источника — в логах будет видно,
        # какой парсер что делает: "hh:Запрос страницы 1..."
        self.logger = logging.getLogger(self.source_name)

    @abstractmethod
    def collect(self) -> list[Vacancy]:
        # Главный метод парсера — собирает вакансии из источника и возвращает их в виде списка объектов Vacancy, напишу его позже
        pass

    def save(self, vacancies: list[Vacancy], filename: Optional[str] = None) -> Path:
        # Сохранение собранных вакансий в JSON-файл
        if filename is None:
            # Формат: hh_2026-05-17_2103.json
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
            filename = f"{self.source_name}_{timestamp}"

        filepath = self.output_dir / f"{filename}.json"

        # Конвертируем все Vacancy в dict (через метод to_dict из модели)
        # Пишем в JSON. ensure_ascii=False, чтобы русские символы  сохранялись как русские, а не как \u-эскейпы.
        # indent=2 — для читаемости файла
        data = [v.to_dict() for v in vacancies]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"Сохранено {len(vacancies)} вакансий в {filepath}")
        return filepath

    def run(self) -> list[Vacancy]:
        # Удобный метод собрать + сохранить сразу
        self.logger.info(f"Запуск парсера {self.source_name}")
        vacancies = self.collect()
        self.logger.info(f"Собрано {len(vacancies)} вакансий")
        self.save(vacancies)
        return vacancies
