# Извлечение зарплаты из текста вакансии.
#
# Заполняет 4 поля Vacancy:
#   - salary_from:     нижняя граница вилки (int) или single value
#   - salary_to:       верхняя граница вилки (int) или None если одно число
#   - salary_currency: "RUR" / "USD" / "EUR" / "JPY" / "KZT" / "USDT"
#   - salary_gross:    True (до налогов), False (на руки), None (не указано / не РФ)
#
# Подход - последовательно пробуем разные паттерны от самого явного к самому
# общему. Первый совпавший паттерн даёт результат.
#
# Покрываемые форматы:
#   "200 000 – 300 000 ₽"        → from=200000, to=300000, RUR
#   "$3 000 – 5 000 / месяц"     → from=3000, to=5000, USD
#   "390 тыс. руб."               → from=390000, currency=RUR
#   "200к-350к ₽"                 → from=200000, to=350000, RUR
#   "150-220 к на руки"           → from=150000, to=220000, RUR (implicit)
#   "100k-150k на руки"           → from=100000, to=150000, RUR (implicit)
#   "до 200к"                     → from=200000, RUR (implicit)
#   "From 150к net"               → from=150000, RUR (implicit), net
#   "2000-2800$"                  → from=2000, to=2800, USD
#   "$8-15k + bonus"              → from=8000, to=15000, USD
#   "9-13k$/month"                → from=9000, to=13000, USD
#   "14-17M JPY"                  → from=14000000, to=17000000, JPY

import re
from typing import Optional

from src.models.vacancy import Vacancy
from src.processors.base import BaseProcessor


# Карта валют: regex-паттерн → код валюты
# Порядок важен — более специфичные перед менее специфичными.
CURRENCY_PATTERNS: list[tuple[str, str]] = [
    (r"USDT|USDC",                              "USDT"),
    (r"₽|руб(?:\.|лей|ля|ль)?|р\.|RUR|RUB",     "RUR"),
    (r"\$|USD|долл(?:ар)?",                     "USD"),
    (r"€|EUR|евро",                             "EUR"),
    (r"¥|JPY|йен",                              "JPY"),
    (r"₸|KZT|тенге",                            "KZT"),
    (r"₴|UAH|гривен",                           "UAH"),
]

# Слова-индикаторы gross/net в радиусе вилки
GROSS_INDICATORS = re.compile(
    r"gross|до\s*налог|до\s*вычет|до\s*ндфл|белая",
    re.IGNORECASE,
)
NET_INDICATORS = re.compile(
    r"\bnet\b|на\s*руки|после\s*налог|чистыми|после\s*вычет",
    re.IGNORECASE,
)

# Слова-маркеры "это про рубли" — если есть в окне рядом с числом + к/тыс/k,
# даже без явной валюты считаем что это RUR.
RUR_CONTEXT_MARKERS = re.compile(
    r"на\s*руки|gross|net|зарплат|оклад|вилка|з\s*/?\s*п|зп\b|"
    r"белая|белой|до\s*налог|до\s*вычет|чистыми|от\s+\d|до\s+\d",
    re.IGNORECASE,
)


class SalaryNormalizer(BaseProcessor):
    name = "salary_normalizer"

    def __init__(self):
        super().__init__()
        self._patterns_with_currency = self._build_patterns_with_currency()
        self._patterns_implicit_rur = self._build_patterns_implicit_rur()

    def process(self, vacancy: Vacancy) -> Vacancy:
        # Не трогаем если зарплата уже задана (например, пришла из hh API).
        if vacancy.salary_from is not None or vacancy.salary_to is not None:
            return vacancy

        if not vacancy.description:
            return vacancy

        text = vacancy.description

        # 1) Сначала ищем паттерны С ЯВНОЙ валютой (надёжнее).
        result = self._try_patterns(text, self._patterns_with_currency, currency_required=True)

        # 2) Если не нашли — пробуем "implicit RUR": число + к/тыс + контекст.
        if result is None:
            result = self._try_patterns(text, self._patterns_implicit_rur, currency_required=False)

        if result is None:
            return vacancy

        salary_from, salary_to, currency, match_position = result

        # Защита от мусорных извлечений: разумные диапазоны.
        if not self._is_reasonable(salary_from, salary_to, currency):
            return vacancy

        # Определяем gross/net по тексту в радиусе match_position.
        gross = self._detect_gross_net(text, match_position, currency)

        vacancy.salary_from = salary_from
        vacancy.salary_to = salary_to
        vacancy.salary_currency = currency
        vacancy.salary_gross = gross

        return vacancy

    # ---------- паттерны с явной валютой ----------

    def _build_patterns_with_currency(self) -> list[re.Pattern]:
        num = r"\d[\d \u00A0\u202F.,]*"
        sep = r"(?:\s*[-–—]\s*|\s+(?:to|до)\s+)"
        currency = r"(?P<currency>" + "|".join(p for p, _ in CURRENCY_PATTERNS) + ")"
        # Множитель — БЕЗ именованной группы.
        mult = r"(?:M(?![a-zA-Z])|М(?![а-яА-Я])|[Мm]лн|[Mm]illion|[Тт]ыс\.?|[Kk]|[кК])?"

        patterns = [
            # 1. Вилка с символом валюты ПОСЛЕ: "200 000 – 300 000 ₽", "2000-2800$"
            re.compile(
                rf"(?P<from>{num})\s*{mult}\s*{sep}\s*(?P<to>{num})\s*(?P<mult_to>{mult})\s*{currency}",
                re.IGNORECASE,
            ),
            # 2. Вилка с валютой ДО числа: "$3 000 – 5 000", "от $200 до $300"
            re.compile(
                rf"{currency}\s*(?P<from>{num})\s*{mult}\s*{sep}\s*"
                rf"(?:{currency.replace('?P<currency>', '?:')}\s*)?(?P<to>{num})\s*(?P<mult_to>{mult})",
                re.IGNORECASE,
            ),
            # 3. Одиночное число с валютой ПОСЛЕ: "390 тыс. руб.", "$3000", "200к ₽"
            re.compile(
                rf"(?P<from>{num})\s*(?P<mult_to>{mult})\s*{currency}",
                re.IGNORECASE,
            ),
            # 4. Валюта ДО одиночного числа: "$3000", "RUR 200 000"
            re.compile(
                rf"{currency}\s*(?P<from>{num})\s*(?P<mult_to>{mult})",
                re.IGNORECASE,
            ),
        ]
        return patterns

    # ---------- паттерны для implicit RUR (без явной валюты) ----------

    def _build_patterns_implicit_rur(self) -> list[re.Pattern]:
        # Тут паттерны без группы currency — валюта будет RUR по умолчанию.
        # Обязательное условие — наличие множителя к/тыс/k, иначе слишком много шума.
        num = r"\d[\d \u00A0\u202F.,]*"
        sep = r"(?:\s*[-–—]\s*|\s+(?:to|до)\s+)"
        # Здесь множитель ОБЯЗАТЕЛЕН (без него получим ложные срабатывания на годах).
        mult_required = r"(?:[Тт]ыс\.?|[Kk]|[кК])"

        patterns = [
            # 1. Вилка с множителями на обеих сторонах: "100k-150k", "150-220 к", "60-160k"
            re.compile(
                rf"(?P<from>{num})\s*(?:{mult_required})?\s*{sep}\s*(?P<to>{num})\s*(?P<mult_to>{mult_required})",
                re.IGNORECASE,
            ),
            # 2. Одиночное число с множителем: "150к", "200K", "до 180К"
            re.compile(
                rf"(?P<from>{num})\s*(?P<mult_to>{mult_required})\b",
                re.IGNORECASE,
            ),
        ]
        return patterns

    # ---------- применение паттернов ----------

    def _try_patterns(
        self,
        text: str,
        patterns: list[re.Pattern],
        currency_required: bool,
    ) -> Optional[tuple[int, Optional[int], str, int]]:
        # Идёт по паттернам, для implicit-RUR дополнительно проверяет
        # что рядом с match есть русский контекст (на руки, зп, оклад и т.п.).

        for pattern in patterns:
            for match in pattern.finditer(text):
                parsed = self._parse_match(match, currency_required=currency_required)
                if parsed is None:
                    continue
                salary_from, salary_to, currency = parsed

                # Для implicit-RUR требуем русский контекст в радиусе ±150 символов.
                if not currency_required:
                    if not self._has_rur_context(text, match.start()):
                        continue

                if self._is_reasonable(salary_from, salary_to, currency):
                    return salary_from, salary_to, currency, match.start()

        return None

    def _parse_match(
        self,
        match: re.Match,
        currency_required: bool,
    ) -> Optional[tuple[int, Optional[int], str]]:
        # Конвертирует regex-match в кортеж (from, to, currency).
        # Если currency_required=False — валюта по умолчанию RUR.
        try:
            if currency_required:
                currency_text = self._safe_group(match, "currency")
                currency = self._normalize_currency(currency_text)
                if currency is None:
                    return None
            else:
                currency = "RUR"

            num_from_text = match.group("from")
            num_from = self._parse_number(num_from_text)
            if num_from is None:
                return None

            mult_text = self._safe_group(match, "mult_to")
            multiplier = self._parse_multiplier(mult_text)

            salary_from = num_from * multiplier

            num_to_text = self._safe_group(match, "to")
            salary_to: Optional[int] = None
            if num_to_text:
                num_to = self._parse_number(num_to_text)
                if num_to is not None:
                    salary_to = num_to * multiplier

            return salary_from, salary_to, currency

        except (IndexError, ValueError, AttributeError):
            return None

    # ---------- утилиты парсинга ----------

    @staticmethod
    def _parse_number(text: str) -> Optional[int]:
        # Конвертирует "200 000", "200.000", "200000" в int.
        # Разные виды пробелов: обычный, NBSP, тонкий.
        # Точка-разделитель ("320.000") трактуется как разделитель тысяч.
        if not text:
            return None
        cleaned = re.sub(r"[ \u00A0\u202F.,]", "", text)
        try:
            return int(cleaned)
        except ValueError:
            return None

    @staticmethod
    def _parse_multiplier(text: Optional[str]) -> int:
        # Возвращает множитель: 1000 для "к"/"тыс", 1000000 для "M"/"млн", иначе 1.
        if not text:
            return 1
        text_lower = text.lower().strip().rstrip(".")
        if text_lower in {"m", "м", "млн", "million"}:
            return 1_000_000
        if text_lower in {"k", "к", "тыс"}:
            return 1_000
        return 1

    @staticmethod
    def _normalize_currency(text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        for pattern, code in CURRENCY_PATTERNS:
            if re.fullmatch(pattern, text, re.IGNORECASE):
                return code
        return None

    @staticmethod
    def _safe_group(match: re.Match, name: str) -> Optional[str]:
        try:
            return match.group(name)
        except (IndexError, KeyError):
            return None

    @staticmethod
    def _has_rur_context(text: str, position: int) -> bool:
        # Проверяет наличие маркеров "это про рубли" в окне ±150 символов
        # вокруг найденного числа. Защита от ложных срабатываний (типа "100 человек").
        start = max(0, position - 150)
        end = min(len(text), position + 150)
        window = text[start:end]
        return bool(RUR_CONTEXT_MARKERS.search(window))

    # ---------- разумность извлечённого ----------

    @staticmethod
    def _is_reasonable(salary_from: int, salary_to: Optional[int], currency: str) -> bool:
        # Защита от ложных срабатываний: проверяем, что числа
        # лежат в разумном диапазоне для МЕСЯЧНОЙ зарплаты.
        #
        # Например, "5+ лет опыта" не должно дать зарплату 5.
        # "В компании 200 человек" не должно дать 200 RUR.

        # Минимум и максимум по валютам (месячная зарплата).
        ranges: dict[str, tuple[int, int]] = {
            "RUR":  (30_000, 5_000_000),       # 30к – 5М рублей
            "USD":  (500, 50_000),             # $500 – $50k
            "EUR":  (500, 50_000),
            "JPY":  (200_000, 30_000_000),     # 200к – 30М йен
            "KZT":  (100_000, 20_000_000),
            "USDT": (500, 50_000),
            "UAH":  (10_000, 1_000_000),
        }

        min_val, max_val = ranges.get(currency, (0, 10**12))

        if salary_from < min_val or salary_from > max_val:
            return False

        if salary_to is not None:
            if salary_to < min_val or salary_to > max_val:
                return False
            if salary_to < salary_from:
                return False

        return True

    #gross / net

    @staticmethod
    def _detect_gross_net(text: str, position: int, currency: str) -> Optional[bool]:
        # Смотрим в окне ±100 символов от позиции найденной зарплаты.
        start = max(0, position - 100)
        end = min(len(text), position + 100)
        window = text[start:end]

        if GROSS_INDICATORS.search(window):
            return True
        if NET_INDICATORS.search(window):
            return False

        # Дефолт по выбору пользователя: для RUB ставим gross.
        if currency == "RUR":
            return True

        return None