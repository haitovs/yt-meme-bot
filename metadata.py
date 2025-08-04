# metadata.py

import random
import re
import json
from config import DESCRIPTION_TEMPLATE_FILE, TAGS_TEMPLATE_FILE, DATABASE_FILE

def _load_last_video_number():
    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            numbers = [item.get("number", 0) for item in data.get("queue", [])]
            return max(numbers, default=99)
    except (FileNotFoundError, json.JSONDecodeError):
        return 99  # Start from 100 if no DB

def _save_video_metadata(video_data):
    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            db = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        db = {"queue": []}

    db["queue"].append(video_data)

    with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2)

def create_video_metadata(user_input: str) -> dict:
    user_input = user_input.strip()
    if len(user_input) < 4:
        user_input = "Random funny content"

    number = _load_last_video_number() + 1
    title = f"{user_input}... memes I found on TikTok #{number}"

    # Load description templates
    with open(DESCRIPTION_TEMPLATE_FILE, encoding='utf-8') as f:
        descriptions = [line.strip() for line in f if line.strip()]
    description = random.choice(descriptions)

    # Generate tags
    tags = generate_tags(user_input)

    metadata = {
        "title": title,
        "description": description,
        "tags": tags,
        "madeForKids": False,
        "number": number
    }

    _save_video_metadata(metadata)
    return metadata

def generate_tags(title: str) -> list:
    title = title.lower()
    tags = set()

    # Load tags from template file
    try:
        with open(TAGS_TEMPLATE_FILE, encoding='utf-8') as f:
            tag_list = json.load(f)
        random_tags = random.sample(tag_list, min(5, len(tag_list)))
        tags.update(random_tags)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Add keywords from title (>= 4 chars)
    keywords = re.findall(r'\b\w{4,}\b', title)
    tags.update(keywords)

    # Create tag list and limit to 500 chars
    sorted_tags = sorted(tags)
    tag_string = ""
    final_tags = []

    for tag in sorted_tags:
        if len(tag_string) + len(tag) + 2 > 495:  # +2 for comma and space
            break
        final_tags.append(tag)
        tag_string += f"{tag}, "

    return final_tags
