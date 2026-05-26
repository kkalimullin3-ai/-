# Извлечение технических навыков из текста вакансии.
#
# Используется ГИБРИДНЫЙ подход:
#   1) Словарь канонических навыков в vacancy.skills (для аналитики)
#      Каждый канонический навык имеет список альтернативных написаний.
#      Например, "python", "py", "питон" -> "Python".
#   2) Парсинг секций "Стек:", "Требования:", "Технологии:" в vacancy.skills_raw

# После первого прогона можно посмотреть частоты skills_raw и обнаружить
# популярные навыки которых нет в SKILLS_DICT - добавить и перезапустить.

import re

from src.models.vacancy import Vacancy
from src.processors.base import BaseProcessor


#тут ничего лучшего через словаря с навыками от клода не нашел
SKILLS_DICT: dict[str, list[str]] = {
    # --- Языки программирования ---
    "Python":      ["python", "питон"],
    "SQL":         ["sql"],
    "R":           [],     # обрабатывается отдельно — нужна особая граница
    "Java":        ["java"],
    "Scala":       ["scala"],
    "C++":         ["c++", "cpp"],
    "C#":          ["c#", "c sharp"],
    "Go":          ["golang"],     # просто "go" слишком неоднозначно
    "Rust":        ["rust"],
    "JavaScript":  ["javascript"],
    "TypeScript":  ["typescript"],
    "Bash":        ["bash", "shell-скрипт", "shell script"],

    # --- СУБД и хранилища ---
    "PostgreSQL":  ["postgresql", "postgres"],
    "MySQL":       ["mysql"],
    "ClickHouse":  ["clickhouse", "кликхаус"],
    "Greenplum":   ["greenplum"],
    "Vertica":     ["vertica"],
    "Oracle":      ["oracle"],
    "MS SQL":      ["mssql", "ms sql", "sql server"],
    "Redis":       ["redis"],
    "MongoDB":     ["mongodb"],
    "S3":          [],     # отдельная обработка
    "Hadoop":      ["hadoop", "hdfs"],
    "Iceberg":     ["iceberg"],
    "Snowflake":   ["snowflake"],
    "DuckDB":      ["duckdb"],
    "Parquet":     ["parquet"],
    "NoSQL":       ["nosql"],
    "Vector DB":   ["vector db", "vector database", "faiss", "milvus", "pinecone", "qdrant", "chroma"],

    # --- BI / Визуализация ---
    "Tableau":     ["tableau", "табло"],
    "Power BI":    ["power bi", "powerbi"],
    "Superset":    ["superset"],
    "Metabase":    ["metabase"],
    "Grafana":     ["grafana"],
    "Looker":      ["looker"],
    "Redash":      ["redash"],
    "DataLens":    ["datalens", "data lens"],

    # --- ETL / Оркестрация ---
    "Airflow":     ["airflow", "эйрфлоу"],
    "Dagster":     ["dagster"],
    "dbt":         [],     # отдельная обработка
    "Spark":       ["spark", "pyspark"],
    "Kafka":       ["kafka", "кафка"],
    "Flink":       ["flink"],
    "Hive":        ["hive"],
    "ETL":         ["etl"],
    "ELT":         ["elt"],
    "RabbitMQ":    ["rabbitmq"],
    "NiFi":        ["nifi"],

    # --- Data Science / ML ---
    "scikit-learn":["scikit-learn", "sklearn", "scikit learn"],
    "CatBoost":    ["catboost"],
    "XGBoost":     ["xgboost"],
    "LightGBM":    ["lightgbm", "lgbm"],
    "PyTorch":     ["pytorch", "torch"],
    "TensorFlow":  ["tensorflow"],
    "pandas":      ["pandas"],
    "NumPy":       ["numpy"],
    "Jupyter":     ["jupyter"],

    # --- LLM / NLP ---
    "LLM":         ["llm", "large language model"],
    "RAG":         [],     # отдельная обработка
    "OpenAI":      ["openai", "chatgpt", "gpt-4"],
    "Claude":      ["claude", "anthropic"],
    "Gemini":      ["gemini"],
    "Mistral":     ["mistral"],
    "Llama":       ["llama", "llama.cpp", "llama-"],
    "LangChain":   ["langchain"],
    "LangGraph":   ["langgraph"],
    "HuggingFace": ["huggingface", "hugging face"],
    "Transformer": ["transformer", "трансформер"],
    "vLLM":        ["vllm"],
    "Quantization":["gguf", "awq", "gptq", "quantization"],
    "SHAP":        ["shap "],

    # --- DevOps / Tools ---
    "Docker":      ["docker"],
    "Kubernetes":  ["kubernetes", "k8s"],
    "Git":         [],     # отдельная обработка
    "GitLab":      ["gitlab"],
    "GitHub":      ["github"],
    "CI/CD":       ["ci/cd", "cicd"],
    "Prometheus":  ["prometheus"],
    "Selenium":    ["selenium"],
    "FFmpeg":      ["ffmpeg"],
    "REST API":    ["rest api", "restful"],

    # --- Аналитика / методология ---
    "A/B testing": ["a/b", "ab-тест", "ab тест", "a/b test", "сплит-тест"],
    "Statistics":  ["статистик", "теория вероятностей", "matstat", "теорвер"],
    "ML":          [],     # отдельная обработка
    "MLOps":       ["mlops"],
    "Time Series": ["time series", "временные ряды"],

    # --- Бизнес-инструменты ---
    "1C":          [],     # отдельная обработка
    "Excel":       ["excel", "эксель"],
    "Google Sheets":["google sheets", "гугл таблиц"],
    "BPMN":        ["bpmn"],
    "UML":         ["uml"],
    "Jira":        ["jira"],
    "Confluence":  ["confluence", "конфлюенс"],

    # --- Языки ---
    "English":     ["english", "английск"],
}

SPECIAL_PATTERNS: dict[str, str] = {
    # R как язык — должно быть отдельным словом, не внутри Rust, R&D и т.п.
    "R":   r"(?:^|[\s,.;:/()])R(?=[\s,.;:/()]|$)",
    # S3 — отдельное слово
    "S3":  r"(?:^|[\s,.;:/()])S3(?=[\s,.;:/()]|$)",
    # dbt — отдельное слово (внутри "doubt" найдётся без этой защиты)
    "dbt": r"(?:^|[\s,.;:/()])dbt(?=[\s,.;:/()]|$)",
    # RAG — отдельное слово
    "RAG": r"(?:^|[\s,.;:/()])RAG(?=[\s,.;:/()]|$)",
    # Git — отдельное слово (не внутри GitLab, GitHub — те ловятся отдельно)
    "Git": r"(?:^|[\s,.;:/()])[Gg]it(?=[\s,.;:/()]|$)",
    # ML — отдельное слово (не внутри HTML, mlops и т.п.)
    "ML":  r"(?:^|[\s,.;:/()])ML(?=[\s,.;:/()]|$)",
    # 1С и 1C (русская и латинская С)
    "1C":  r"(?:^|[\s,.;:/()])1[CС](?=[\s,.;:/()]|$)",
}

# Регулярка для поиска секций "Стек:", "Требования:", "Технологии:" и подобных.
# Захватывает заголовок секции и текст до следующей секции или 2+ переводов строки.
SECTION_HEADERS = [
    "стек", "стэк", "tech stack", "technologies", "технолог",
    "требования", "requirements", "что нужно",
    "ключевые требования", "ожидаем", "что важно",
    "будет плюсом", "nice to have", "будет преимуществом",
    "обязательно", "must have", "стек технологий",
]
SECTION_PATTERN = re.compile(
    # Заголовок (с * или ** для markdown) + двоеточие
    r"[*_#\s]*(?:" + "|".join(SECTION_HEADERS) + r")[*_:\s]*[:\-—]\s*"
    # Содержимое — до пустой строки или конца текста
    r"(.+?)(?=\n\s*\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# Регулярка для разбиения секции на отдельные технологии.
# Разделители: запятая, слэш, точка с запятой, маркеры списков (•, ▪, -, *).
SPLIT_PATTERN = re.compile(r"[,;/\n•▪►·\-*]+")


class SkillExtractor(BaseProcessor):
    name = "skill_extractor"

    def __init__(self):
        super().__init__()

        # Предкомпилируем регулярки для словарных навыков
        self._dict_patterns: dict[str, re.Pattern] = {}
        for canonical, variants in SKILLS_DICT.items():
            if not variants:
                # Пустой список - скип
                continue
            # обрабатываем специальнве симвалы как в яп с++ и с#
            escaped = [re.escape(v) for v in variants]
            pattern = "|".join(escaped)
            self._dict_patterns[canonical] = re.compile(pattern, re.IGNORECASE)

        # Особые регулярки с границами слов
        self._special_patterns: dict[str, re.Pattern] = {}
        for canonical, raw_pattern in SPECIAL_PATTERNS.items():
            self._special_patterns[canonical] = re.compile(raw_pattern)

    def process(self, vacancy: Vacancy) -> Vacancy:
        # Если описания нет - пропускаем, без падений
        if not vacancy.description:
            return vacancy

        text = vacancy.description

        # КАНОНИЧЕСКИЕ навыки через словарь
        vacancy.skills = self._extract_canonical(text)

        # СЫРЫЕ навыки из секций "Стек:", "Требования:" и т.п
        vacancy.skills_raw = self._extract_from_sections(text)

        return vacancy

    def _extract_canonical(self, text: str) -> list[str]:
        # Ищем все канонические навыки в тексте
        # Используем set для устранения дублей
        # Возвращаем отсортированный список для стабильного порядка
        found: set[str] = set()

        # Обычные словарные навыки
        for canonical, pattern in self._dict_patterns.items():
            if pattern.search(text):
                found.add(canonical)

        # Особые с границами слов
        for canonical, pattern in self._special_patterns.items():
            if pattern.search(text):
                found.add(canonical)

        return sorted(found)

    def _extract_from_sections(self, text: str) -> list[str]:
        # Парсим секции "Стек:", "Требования:" и извлекаем технологии-кандидаты
        # Сохраняем словосочетания целиком (например "big data", "scikit-learn")
        candidates: set[str] = set()

        for match in SECTION_PATTERN.finditer(text):
            section_content = match.group(1)

            # Разбиваем на куски по запятым, слэшам, маркерам списков
            chunks = SPLIT_PATTERN.split(section_content)

            for chunk in chunks:
                # Чистим markdown-разметку, пробелы по краям, точки в конце
                chunk = re.sub(r"[*_`]+", "", chunk).strip().strip(".,;:")

                # Если кусок начинается не с буквы/цифры — пропускаем
                if not chunk or not re.match(r"[A-Za-zА-Яа-я0-9]", chunk):
                    continue

                # Берём только латинско-цифровую часть с возможными . _ + # / -
                # (типичные символы в названиях технологий).
                clean = re.match(r"[A-Za-z][A-Za-z0-9+#./_\- ]{1,40}", chunk)
                if not clean:
                    continue

                word = clean.group(0).strip().strip(".,;:-").lower()

                # Фильтр: длина и стоп-слова.
                if len(word) < 3 or len(word) > 30:
                    continue
                if word in STOP_WORDS:
                    continue

                candidates.add(word)

        return sorted(candidates)


# Стоп-слова - частые слова из текстов вакансий, которые НЕ являются технологиями.
# Расширяй этот список после первого прогона, посмотрев частоты в skills_raw.
STOP_WORDS = {
    # --- Общие слова о вакансии ---
    "опыт", "знание", "знания", "уверенный", "уверенное", "владение",
    "понимание", "умение", "навык", "навыки", "level",
    # --- Английские служебные ---
    "the", "and", "or", "etc", "and/or", "with", "have", "must", "should",
    "would", "will", "for", "from", "well", "good", "great", "strong",
    "deep", "solid", "in", "on", "at", "of", "to", "by", "as",
    "knowledge", "experience", "skill", "skills", "ability", "understanding",
    # --- Цифры в одиночку ---
    "год", "года", "лет", "от", "до", "или", "и",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    "10", "20", "30", "100", "200", "500", "1000",
    # --- Часто встречаемое не-техническое ---
    "team", "lead", "senior", "middle", "junior", "intern", "stage",
    "сеньор", "миддл", "джуниор", "стажер", "стажёр",
    "remote", "office", "hybrid", "удалёнка", "удаленка", "офис",
    "fulltime", "parttime", "full", "part", "time",
    # --- Фрагменты технологий, которые не имеют смысла отдельно ---
    "data", "big", "open", "learn", "source", "stack", "engineer",
    "ai", "dl", "ml", "ds", "qa",  # — есть в SKILLS_DICT, тут отсекаем дубли
    "ci", "cd",                     # — фрагменты "ci/cd"
    "air",                          # — часть airflow
    "scikit",                       # — часть scikit-learn
    "rest", "api",                  # — слишком общие
    # --- Общие термины разработки ---
    "production", "system", "systems", "code", "coding", "development",
    "intermediate", "advanced", "basic", "junior+",
    "architecture", "backend", "frontend", "fullstack",
    "ownership", "mindset", "ecosystem", "environments", "environment",
    "deployment", "engineering", "grade",
    "bootstrap", "cis",
    "evaluation", "hold", "outs",
    # --- Общие даты/направления ---
    "eastern", "gmt", "cst", "pst",
}