import feedparser
import os
import re
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from datetime import datetime
from email.utils import parsedate_to_datetime

RSS_URL = "https://rss.blog.naver.com/ewigenostalgie.xml"
POSTS_DIR = "_posts"

os.makedirs(POSTS_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def slugify(text):
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:80] or "post"

def escape_yaml(text):
    return text.replace("\\", "\\\\").replace('"', "'")

def extract_blog_info(url):
    """
    RSS 링크 예:
    https://blog.naver.com/ewigenostalgie/224257076014?fromRss=true
    """
    m = re.search(r"blog\.naver\.com/([^/?#]+)/(\d+)", url)
    if not m:
        return None, None
    return m.group(1), m.group(2)

def fetch_naver_body(original_url):
    blog_id, log_no = extract_blog_info(original_url)

    if blog_id and log_no:
        url = (
            "https://blog.naver.com/PostView.naver"
            f"?blogId={blog_id}&logNo={log_no}"
            "&redirect=Dlog&widgetTypeCall=true"
            "&directAccess=false"
        )
    else:
        url = original_url

    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        res.raise_for_status()
    except Exception:
        return ""

    soup = BeautifulSoup(res.text, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    selectors = [
        "div.se-main-container",
        "div#postViewArea",
        "div.post_ct",
        "div.se_component_wrap",
    ]

    body = None
    for selector in selectors:
        body = soup.select_one(selector)
        if body:
            break

    if not body:
        return ""

    text = md(str(body), heading_style="ATX")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text

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

    body = fetch_naver_body(link)

    if not body:
        body = entry.get("summary", "")

    content = f"""---
title: "{escape_yaml(title)}"
date: {datetime_str}
original_url: "{link}"
source: "Naver Blog"
---

원문: {link}

---

{body}
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

print("Sync complete.")