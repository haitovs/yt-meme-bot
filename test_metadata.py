# test_metadata.py

import os
import json
from metadata import create_video_metadata
from config import DATABASE_FILE

def test_create_video_metadata():
    # 1. Очистим базу перед тестом
    if os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            json.dump({"queue": []}, f)

    # 2. Тестовая строка
    user_input = "angry cat"

    # 3. Создаём метаданные
    metadata = create_video_metadata(user_input)

    # 4. Проверки
    assert isinstance(metadata, dict)
    assert "title" in metadata and "cat" in metadata["title"]
    assert "description" in metadata and isinstance(metadata["description"], str)
    assert "tags" in metadata and isinstance(metadata["tags"], list)
    
    total_tag_chars = sum(len(tag) for tag in metadata["tags"]) + 2 * len(metadata["tags"])
    assert total_tag_chars < 500, f"Tags too long: {total_tag_chars} chars"
    assert metadata["madeForKids"] is False

    # 5. Проверим запись в файл
    with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        assert "queue" in data and len(data["queue"]) == 1
        assert data["queue"][0]["title"] == metadata["title"]

    print("✅ test_create_video_metadata passed!")
    print(metadata)

if __name__ == "__main__":
    test_create_video_metadata()
