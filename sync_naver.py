import feedparser
import os
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

RSS_URL = "https://rss.blog.naver.com/ewigenostalgie.xml"
POSTS_DIR = "_posts"

os.makedirs(POSTS_DIR, exist_ok=True)

def slugify(text):
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:60] or "post"

feed = feedparser.parse(RSS_URL)

for entry in feed.entries:
    title = entry.get("title", "Untitled")
    link = entry.get("link", "")

    published = entry.get("published", "")
    if published:
        dt = parsedate_to_datetime(published)
    else:
        dt = datetime.now()

    date_str = dt.strftime("%Y-%m-%d")
    datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S %z")

    slug = slugify(title)
    filename = f"{date_str}-{slug}.md"
    filepath = os.path.join(POSTS_DIR, filename)

    if os.path.exists(filepath):
        continue

    summary = entry.get("summary", "")

    content = f"""---
title: "{title.replace('"', "'")}"
date: {datetime_str}
original_url: "{link}"
source: "Naver Blog"
---

원문: {link}

---

{summary}
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

print("Sync complete.")