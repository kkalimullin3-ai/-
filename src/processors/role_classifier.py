#   1. Для каждой роли считаем число её ключевых слов в первых 500 символах.
#   2. Берём роль с максимальным счётом.
#   3. Если 0 совпадений в "other".
#
# Почему первые 500 символов:
#   Роль обычно явно в заголовке и в первых строках поста.
#   Дальше идут требования, где упоминаются смежные технологии и роли -
#   это создаёт шум.

import re

from src.models.vacancy import Vacancy
from src.processors.base import BaseProcessor


SEARCH_WINDOW = 500

ROLE_KEYWORDS: dict[str, list[str]] = {
    "product_analyst": [
        r"\bproduct\s+analyst\b",
        r"\bпродуктов\w+\s+аналитик\w*",
        r"\bproductanalyst\b",
        r"#productanalyst",
        r"\bpa\b",
    ],
    "data_analyst": [
        r"\bdata\s+analyst\b",
        r"\baналитик\w*\s+данных\b",
        r"\bдата[-\s]+аналитик\w*",
        r"\bdataanalyst\b",
        r"#dataanalyst",
        r"\bda\b",
        r"\baналитик\w+\s+данных\b",
        r"\baналитика\s+данных\b",
    ],
    "ml_engineer": [
        r"\bml\s+engineer\b",
        r"\bmachine\s+learning\s+engineer\b",
        r"\bмл[-\s]+инженер\w*",
        r"\bml[-\s]+инженер\w*",
        r"\bml\s+specialist\b",                  # ML Specialist
        r"\bmlengineer\b",
        r"#machinelearning",
        r"#mlинженер",
        r"\bвакансия:\s*ml\b",                   # "Вакансия: ML"
        r"\bищем\s+ml\b",                        # "Ищем ML"
        r"#ml\b",                                # тег #ML отдельно (но проверяется по счёту)
    ],
    "data_scientist": [
        r"\bdata\s+scientist\b",
        r"\bdata\s+science\s+specialist\b",
        r"\bдата[-\s]+сайентист\w*",
        r"\bдата[-\s]+саентист\w*",
        r"\bdatascientist\b",
        r"#datascientist",
        r"#datascience",
        r"\bds\b",
        r"\bnlp\s+engineer\b",
        r"\bnlp\s+data\s+scientist\b",
        r"\bnlp\s+developer\b",                  # NLP Developer
        r"\bcv\s+engineer\b",
        r"\bcv[-\s]+инженер\w*",
        r"\bcomputer\s+vision\s+engineer\b",
        r"\bcomputer\s+vision\s+engin",          # "Computer Vision Engin..." (обрезано markdown)
        r"\bdeep\s+learning\s+engineer\b",
        r"\bdl\s+engineer\b",
        r"\bresearcher\b",
    ],
    "data_engineer": [
        r"\bdata\s+engineer\b",
        r"\bдата[-\s]+инженер\w*",
        r"\bdataengineer\b",
        r"\bdataengeneer\b",                     # частая опечатка
        r"\bdata\s+engeneer\b",                  # частая опечатка
        r"#dataengineer",
        r"#dataengeneer",
        r"\bde\b",
        r"\bdwh\b",
        r"\betl\s+engineer\b",
        r"\bdwh[-\s]+разработчик\w*",
        r"\bdata\s+инженер\w*",                  # смесь языков
        r"\bdatabase\s+engineer\b",              # Database Engineer
    ],
    "bi_analyst": [
        r"\bbi\s+analyst\b",
        r"\bbi[-\s]+аналитик\w*",
        r"\banalytics\s+engineer\b",
        r"\bdata\s+analytics\s+engineer\b",
        r"\bbianalyst\b",
    ],
    "business_analyst": [
        r"\bбизнес[-\s]+аналитик\w*",
        r"\bbusiness\s+analyst\b",
        r"\bbuisness\s+analyst\b",
    ],
    "system_analyst": [
        r"\bсистемный\s+аналитик\w*",
        r"\bsystem\s+analyst\b",
        r"\bsystems\s+analyst\b",
    ],
    "quant": [
        r"\bquant\b",
        r"\bquantitative\s+researcher\b",
        r"\bquantitative\s+analyst\b",
        r"\bquantitative\s+trader\b",
        r"\bhft\b",
        r"\bquant\s+researcher\b",
    ],
    "ai_engineer": [
        r"\bai\s+engineer\b",
        r"\bai[-\s]+инженер\w*",
        r"\bllm\s+engineer\b",
        r"\bllm\s+application\s+engineer\b",
        r"\bprompt\s+engineer\b",
        r"\bпромпт[-\s]+инженер\w*",
        r"\bagent\s+engineer\b",
        r"\bai[-\s]+разработчик\w*",
        r"\bai\s+architect\b",
        r"\bai\s+&\s+data\s+solutions\s+architect\b",   # AI & Data Solutions Architect
        r"\bai\s+tech\s+lead\b",
        r"\bai\s+generalist\b",
        r"\bai[-\s]+генералист\w*",
        r"\bai\s+product\s+engineer\b",
        r"\bhead\s+of\s+ai\b",                          # Head of AI
        r"\bруководитель\s+направления\s+ии\b",
        r"\bai\s+pipeline\s+engineer\b",                # AI Pipeline Engineer
        r"\bgenerative\s+video\s+engineer\b",           # Generative Video Engineer
    ],
    "mlops_engineer": [
        r"\bmlops\b",
        r"\bmlops[-\s]+инженер\w*",
        r"\bml\s+ops\b",
        r"\bllmops\b",
        r"\bml\s+platform\s+engineer\b",
        r"\bml\s+infrastructure\s+engineer\b",
        r"\brелиз[-\s]+инженер\w*\s+(?:с\s+)?функц\w+\s+mlops",
        r"#mlops",
    ],
}


class RoleClassifier(BaseProcessor):
    name = "role_classifier"

    def __init__(self):
        super().__init__()
        # Предкомпилируем регулярки.
        # Структура: {role_name: [pattern1, pattern2, ...]}
        self._patterns: dict[str, list[re.Pattern]] = {}
        for role, keywords in ROLE_KEYWORDS.items():
            self._patterns[role] = [
                re.compile(kw, re.IGNORECASE) for kw in keywords
            ]

    def process(self, vacancy: Vacancy) -> Vacancy:
        # Не трогаем если роль уже задана.
        if vacancy.role_canonical is not None:
            return vacancy

        if not vacancy.description:
            return vacancy

        # Окно поиска - title + начало description.
        # Title очень важен, потому что там часто прямо указана роль.
        text = (vacancy.title or "") + " " + vacancy.description[:SEARCH_WINDOW]

        vacancy.role_canonical = self._classify(text)
        return vacancy

    def _classify(self, text: str) -> str:
        # Подсчитываем количество совпадений для каждой роли.
        scores: dict[str, int] = {}
        for role, patterns in self._patterns.items():
            scores[role] = sum(1 for p in patterns if p.search(text))

        # Приоритетное правило: если есть quant/HFT/trading — это quant,
        # даже если в посте упоминается ML/Python/...
        if scores["quant"] > 0:
            return "quant"

        # Берём роль с максимальным счётом.
        best_role = max(scores, key=scores.get)

        # Если ни одно слово не нашлось - это не аналитика.
        if scores[best_role] == 0:
            return "other"

        return best_role