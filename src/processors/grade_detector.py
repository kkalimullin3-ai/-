# Определение уровня вакансии. Заполняет два независимых поля:
#
#   1) grade — категориальный уровень (junior/middle/senior/lead)
#      Только если в тексте есть явные слова: "Senior ML Engineer",
#      "Junior+", "Middle/Senior" и т.п.
#
#   2) experience_years_from / experience_years_to — числовые годы опыта
#      Если в тексте есть фразы вида "от 3 лет", "3-5 years", "5+ лет".
#
# Окна поиска ДВА разных:
#   - GRADE -узкое (500 chars), потому что грейд явно указывают
#     в заголовке или начале поста. Расширять окно опасно: в требованиях
#     встречаются фразы вроде "опыт senior разработки" - это не значит,
#     что вакансия senior.
#   - EXPERIENCE - широкое (3000 chars), потому что требования с опытом
#     обычно после описания компании, в середине-конце поста.

import re

from src.models.vacancy import Vacancy
from src.processors.base import BaseProcessor


SEARCH_WINDOW_GRADE = 500          # для grade - узкое окно (заголовок + начало)
SEARCH_WINDOW_EXPERIENCE = 3000    # для опыта - широкое окно (захватывает раздел требований)


# Паттерны для GRADE (явные слова)

LEAD_PATTERNS = [
    r"\bteam\s*lead\b",
    r"\btech\s*lead\b",
    r"\bhead\s*of\b",
    r"\bтимлид\b",
    r"\bтим\s*лид\b",
    r"\bруководитель\b",
    r"\bначальник\b",
    r"\blead\b(?!\s*to\b)",     # "lead" но не "lead to"
]

SENIOR_PATTERNS = [
    r"\bsenior\b",
    r"\bсениор\b",
    r"\bсеньор\b",
    r"\bsr\.?\b",
    r"\bстарший\b",
]

MIDDLE_PATTERNS = [
    r"\bmiddle\b",
    r"\bmid\b",
    r"\bмиддл\b",
    r"\bмидл\b",
    r"\bmidlle\b",            # частая опечатка в постах
]

JUNIOR_PATTERNS = [
    r"\bjunior\b",
    r"\bjr\.?\b",
    r"\bджуниор\b",
    r"\bджун\b",
    r"\bмладший\b",
    r"\bintern\b",
    r"\bстажер\b",
    r"\bстажёр\b",
    r"\bстажировк\w*",
]

# Повышающие модификаторы — "Junior+" → middle, "Middle+" → senior
JUNIOR_PLUS_PATTERNS = [
    r"\bjunior\s*\+",
    r"\bджуниор\s*\+",
    r"\bjunior\s*/\s*middle",
]
MIDDLE_PLUS_PATTERNS = [
    r"\bmiddle\s*\+",
    r"\bмиддл\s*\+",
    r"\bмидл\s*\+",
    r"\bmidlle\s*\+",           # опечатка с плюсом
    r"\bmiddle\s*/\s*senior",
]


EXPERIENCE_PATTERN = re.compile(
    r"(?:от\s+|from\s+|не\s*менее\s+|минимум\s+)?"          # опц "от"/"from"/"не менее"/"минимум"
    r"(\d+)"                                                 # первое число
    r"(?:[.,]\s*\d+)?"                                       # опц десятичная часть (1.5 / 1,5)
    r"(?:"
        r"\s*[-–—]\s*(\d+)(?:\s*\+)?"                        # диапазон через тире (с возможным +)
        r"|"
        r"\s*(?:до|to)\s+(\d+)"                              # диапазон через "до"/"to"
        r"|"
        r"\s*\+"                                             # "+" — "3+ лет"
    r")?"
    r"\s*"
    r"(?:лет|год[аoы]?|years?[''’]?\s*|yrs?\.?)",            # единица: лет, года, year(s), yr(s)
    re.IGNORECASE,
)

# Контекст вокруг числа — это должно быть про опыт работы.
# Расширенный: опыт, стаж, experience, years, работа, разработка, коммерческий, профессиональный.
EXPERIENCE_CONTEXT = re.compile(
    r"опыт|стаж|experience|years?|"
    r"работ\w*|разработк\w*|"
    r"коммерческ\w*|"
    r"профессион\w*",
    re.IGNORECASE,
)

# Анти-контекст — фразы, которые означают НЕ опыт работы кандидата.
# Срабатывает в окне поиска — если есть, пропускаем match.
EXPERIENCE_ANTI_CONTEXT = re.compile(
    r"с\s+(?:19|20)\d\d\s*года|"        # "с 2018 года" — стаж компании на рынке
    r"(?:19|20)\d\d\s*году?|"           # "2025 году" / "в 2025 году"
    r"наш\w*\s+\d+\s*лет|"              # "нашей компании 5 лет"
    r"на\s+рынк[еа]",                   # "10 лет на рынке"
    re.IGNORECASE,
)


class GradeDetector(BaseProcessor):
    name = "grade_detector"

    def __init__(self):
        super().__init__()
        self._lead         = self._compile(LEAD_PATTERNS)
        self._senior       = self._compile(SENIOR_PATTERNS)
        self._middle       = self._compile(MIDDLE_PATTERNS)
        self._junior       = self._compile(JUNIOR_PATTERNS)
        self._junior_plus  = self._compile(JUNIOR_PLUS_PATTERNS)
        self._middle_plus  = self._compile(MIDDLE_PLUS_PATTERNS)

    @staticmethod
    def _compile(patterns: list[str]) -> list[re.Pattern]:
        return [re.compile(p, re.IGNORECASE) for p in patterns]

    @staticmethod
    def _any_match(patterns: list[re.Pattern], text: str) -> bool:
        return any(p.search(text) for p in patterns)

    def process(self, vacancy: Vacancy) -> Vacancy:
        # Не трогаем поля если уже заполнены (например из hh API).
        if vacancy.grade is not None and vacancy.experience_years_from is not None:
            return vacancy

        if not vacancy.description:
            return vacancy

        title = vacancy.title or ""

        # GRADE - узкое окно. Грейд обычно явно в заголовке или начале поста.
        # Расширять окно опасно: в требованиях встречаются фразы вроде
        # "опыт senior разработки" - это не значит, что вакансия senior.
        if vacancy.grade is None:
            text_for_grade = title + " " + vacancy.description[:SEARCH_WINDOW_GRADE]
            vacancy.grade = self._detect_grade(text_for_grade)

        # ОПЫТ - широкое окно. Требования с опытом обычно после описания
        # компании, в середине-конце поста.
        if vacancy.experience_years_from is None:
            text_for_exp = title + " " + vacancy.description[:SEARCH_WINDOW_EXPERIENCE]
            years_from, years_to = self._detect_experience(text_for_exp)
            vacancy.experience_years_from = years_from
            vacancy.experience_years_to = years_to

        return vacancy

    # grade

    def _detect_grade(self, text: str) -> str | None:
        # Порядок проверок:
        # 1) Повышающие модификаторы (Junior+, Middle/Senior) - раньше базовых,
        #    иначе "Middle+" сматчится как middle.


        if self._any_match(self._middle_plus, text):
            return "senior"
        if self._any_match(self._junior_plus, text):
            return "middle"

        if self._any_match(self._lead, text):
            return "lead"
        if self._any_match(self._senior, text):
            return "senior"
        if self._any_match(self._middle, text):
            return "middle"
        if self._any_match(self._junior, text):
            return "junior"

        return None

    # опыт

    @staticmethod
    def _detect_experience(text: str) -> tuple[int | None, int | None]:
        # Ищет в тексте фразу про опыт работы в годах.
        # Возвращает (from, to) - нижнюю и верхнюю границу.
        #
        # Алгоритм:
        #   1. Для каждого match числа+единицы (лет/year/...)
        #   2. Берём окно ±80 символов вокруг.
        #   3. Проверяем что есть EXPERIENCE_CONTEXT (опыт/стаж/работа/...).
        #   4. Проверяем что НЕТ EXPERIENCE_ANTI_CONTEXT
        #      ("с 2018 года", "на рынке", "наш N лет").
        #   5. Парсим число и опциональный диапазон.
        #
        # Защита от ложных:
        #   - число должно быть в пределах 0-20 лет
        #   - диапазон должен быть валидным (from <= to)

        for match in EXPERIENCE_PATTERN.finditer(text):
            position = match.start()
            window_start = max(0, position - 80)
            window_end = min(len(text), match.end() + 80)
            window = text[window_start:window_end]

            # Должно быть слово про опыт.
            if not EXPERIENCE_CONTEXT.search(window):
                continue

            # Не должно быть анти-контекста (год компании, "на рынке").
            if EXPERIENCE_ANTI_CONTEXT.search(window):
                continue

            try:
                years_from = int(match.group(1))
            except (TypeError, ValueError):
                continue

            # Разумные пределы.
            if years_from < 0 or years_from > 20:
                continue

            # Парсим верхнюю границу: либо группа 2 (через тире),
            # либо группа 3 (через "до"/"to"), либо None.
            years_to = None
            for group_idx in (2, 3):
                try:
                    val = match.group(group_idx)
                    if val:
                        years_to = int(val)
                        break
                except (TypeError, ValueError, IndexError):
                    continue

            # Валидация диапазона.
            if years_to is not None:
                if years_to < years_from or years_to > 20:
                    years_to = None

            return years_from, years_to

        return None, None