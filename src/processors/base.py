# Базовый класс для всех процессоров
# Архитектурно повторяет BaseParser: задаёт абстрактный метод process() и общую обёртку process_all()
#  raw Vacancy -> SkillExtractor -> SalaryNormalizer -> GradeDetector -> RoleClassifier
import logging
from abc import ABC, abstractmethod

from tqdm import tqdm

from src.models.vacancy import Vacancy


class BaseProcessor(ABC):
    # Имя процессора. Переопределяется наследниками, используется в логах и прогресс-баре.
    name: str = "base"

    def __init__(self):
        # Логгер с именем процессора. Имя пишется в каждую строку лога,
        # чтобы видеть какой процессор что делает в общем пайплайне.
        self.logger = logging.getLogger(self.name)

    @abstractmethod
    def process(self, vacancy: Vacancy) -> Vacancy:
        # Главный метод - обогащает одну вакансию.
        # Каждый наследник переопределяет его под свою логику:
        #   SkillExtractor.process()     заполняет vacancy.skills
        #   SalaryNormalizer.process()  заполняет salary_from/to/currency/gross
        #   GradeDetector.process()      заполняет vacancy.grade
        #   RoleClassifier.process()     заполняет vacancy.role_canonical

        # Возвращает ту же Vacancy с обновлёнными полями.
        # Не создаёт новый объект — мутирует существующий.
        ...

    def process_all(self, vacancies: list[Vacancy]) -> list[Vacancy]:
        # Общая обёртка для прогона списка вакансий через process().
        # Используется в раннере build_dataset.py.

        self.logger.info(f"Запуск {self.name} для {len(vacancies)} вакансий")

        for vacancy in tqdm(vacancies, desc=self.name):
            self.process(vacancy)

        self.logger.info(f"{self.name}: обработано {len(vacancies)} вакансий")
        return vacancies