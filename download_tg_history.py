import logging

from src.parsers.tg_parser import TgParser

# Список каналов, которые качаем, можно добавлять с кайфом
CHANNELS = [
    "@datasciencejobs",
    "@vacancy_cs",
    "@foranalysts",
    "@nodatanojobs"
]


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Создаём парсер БЕЗ лимита сообщений и БЕЗ фильтров.
    # messages_per_channel=None - качать всю историю канала до самого первого поста.
    # apply_filters=False - не отсекать по ключевым словам, фильтрация будет в процессорах.
    parser = TgParser(
        channels=CHANNELS,
        messages_per_channel=None,
        apply_filters=False,
    )

    print("\n Начинаем скачивание полной истории")
    print(f"Каналов: {len(CHANNELS)}")
    print("Каждый канал сохраняется в свой файл по мере готовности.\n")

    vacancies = parser.collect()

    print(f"\n Готово")
    print(f"Всего собрано: {len(vacancies)} постов")
    print(f"Файлы лежат в data/raw/telegram_<channel>.json")


if __name__ == "__main__":
    main()