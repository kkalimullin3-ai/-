# Раннер пайплайна обработки.
#
# Делает три вещи:
#   1) Загружает все telegram_*.json из data/raw/
#   2) Прогоняет через все процессоры (T2)
#   3) Сохраняет результат в data/processed/vacancies.json
#
# Запускается из корня проекта:  python build_dataset.py
#
# После запуска можно открыть data/processed/vacancies.json
# и увидеть полностью обогащённые вакансии с заполненными
# salary_from, salary_to, skills, grade, role_canonical и т.д.

import json
import logging
from datetime import datetime
from pathlib import Path

from src.models.vacancy import Vacancy
from src.processors.skill_extractor import SkillExtractor
from src.processors.salary_normalizer import SalaryNormalizer
from src.processors.grade_detector import GradeDetector
from src.processors.role_classifier import RoleClassifier


# Настройка логирования - INFO уровень покажет каждый шаг пайплайна.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")


RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
OUTPUT_FILE = PROCESSED_DIR / "vacancies.json"


def _load_raw_vacancies() -> list[Vacancy]:
    # Грузит все telegram_*.json из data/raw/ в список Vacancy объектов.
    # Один файл = один канал, в нём массив вакансий.
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    json_files = sorted(RAW_DIR.glob("telegram_*.json"))
    if not json_files:
        raise FileNotFoundError(
            f"Нет JSON-файлов в {RAW_DIR}. "
            "Сначала запусти download_tg_history.py для скачивания вакансий."
        )

    all_vacancies: list[Vacancy] = []
    for path in json_files:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data:
            # Парсим даты обратно из строк ISO формата.
            published_at = item.get("published_at")
            if isinstance(published_at, str):
                try:
                    published_at = datetime.fromisoformat(published_at)
                except ValueError:
                    published_at = None

            v = Vacancy(
                source=item["source"],
                source_id=item["source_id"],
                title=item["title"],
                employer=item.get("employer"),
                city=item.get("city"),
                url=item.get("url"),
                description=item.get("description"),
                search_query=item.get("search_query"),
                search_position=item.get("search_position"),
                published_at=published_at,
                raw=item.get("raw"),
            )
            all_vacancies.append(v)

        log.info(f"  {path.name}: загружено {len(data)} вакансий")

    log.info(f"Всего загружено: {len(all_vacancies)} вакансий из {len(json_files)} файлов")
    return all_vacancies


def _save_vacancies(vacancies: list[Vacancy]) -> None:
    # Сохраняем обогащённые вакансии в JSON.
    # JSON-формат выбран для читаемости - можно открыть в любом редакторе
    # и увидеть результат работы процессоров.
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    data = [v.to_dict() for v in vacancies]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)
    log.info(f"Сохранено в {OUTPUT_FILE}: {len(data)} вакансий, {size_mb:.1f} МБ")


def _print_summary(vacancies: list[Vacancy]) -> None:
    # Итоговая статистика по датасету - для финального ощущения качества.
    from collections import Counter

    total = len(vacancies)

    # Зарплата
    with_salary = sum(1 for v in vacancies if v.salary_from is not None)

    # Грейд
    grade_stats = Counter(v.grade or "не определён" for v in vacancies)

    # Опыт
    with_exp = sum(1 for v in vacancies if v.experience_years_from is not None)

    # Роли
    role_stats = Counter(v.role_canonical or "не определён" for v in vacancies)

    # Навыки
    skill_counts = [len(v.skills) for v in vacancies]
    avg_skills = sum(skill_counts) / len(skill_counts) if skill_counts else 0

    print("\n" + "=" * 60)
    print(f"ИТОГОВАЯ СТАТИСТИКА (всего {total} вакансий)")
    print("=" * 60)

    print(f"\nЗарплата извлечена: {with_salary} ({100 * with_salary // total}%)")
    print(f"Опыт извлечён:      {with_exp} ({100 * with_exp // total}%)")
    print(f"Среднее число навыков на вакансию: {avg_skills:.1f}")

    print("\nРаспределение грейдов:")
    for g, c in grade_stats.most_common():
        print(f"  {c:5d} × {g:18s} ({100 * c / total:.1f}%)")

    print("\nРаспределение ролей:")
    for r, c in role_stats.most_common():
        print(f"  {c:5d} × {r:18s} ({100 * c / total:.1f}%)")


def main():
    log.info("=== Запуск пайплайна обогащения вакансий ===")

    # Загрузка сырых данных.
    log.info("Шаг 1: загрузка сырых данных из data/raw/...")
    vacancies = _load_raw_vacancies()

    # Прогон через все процессоры по очереди.
    # Порядок важен лишь логически (на работу каждого процессора
    # другие не влияют - они заполняют разные поля Vacancy).
    log.info("Шаг 2: прогон через процессоры...")

    processors = [
        SkillExtractor(),
        SalaryNormalizer(),
        GradeDetector(),
        RoleClassifier(),
    ]

    for processor in processors:
        log.info(f"  -> {processor.name}")
        processor.process_all(vacancies)

    # Сохранение.
    log.info("Шаг 3: сохранение в data/processed/...")
    _save_vacancies(vacancies)

    # Финальная статистика.
    _print_summary(vacancies)

    log.info("=== Пайплайн завершён ===")


if __name__ == "__main__":
    main()