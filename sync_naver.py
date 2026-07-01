import os
import re
import glob
import html
import feedparser
import requests
import unicodedata
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from datetime import datetime
from email.utils import parsedate_to_datetime

RSS_URL = "https://rss.blog.naver.com/ewigenostalgie.xml"
BLOG_ID = "ewigenostalgie"
POSTS_DIR = "_posts"

os.makedirs(POSTS_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": f"https://blog.naver.com/{BLOG_ID}",
}


def clean_text(text):
    if not text:
        return ""
    text = html.unescape(str(text))
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def slugify(text):
    text = clean_text(text)
    text = re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:80] or "post"


def escape_yaml(text):
    return clean_text(text).replace("\\", "\\\\").replace('"', "'")


def extract_blog_info(url):
    m = re.search(r"blog\.naver\.com/([^/?#]+)/(\d+)", url)
    if not m:
        return BLOG_ID, None
    return m.group(1), m.group(2)


def post_view_url(blog_id, log_no):
    return (
        "https://blog.naver.com/PostView.naver"
        f"?blogId={blog_id}"
        f"&logNo={log_no}"
        "&redirect=Dlog"
        "&widgetTypeCall=true"
        "&directAccess=false"
    )


def fetch_naver_body(link):
    blog_id, log_no = extract_blog_info(link)

    if not log_no:
        return ""

    url = post_view_url(blog_id, log_no)

    try:
        res = requests.get(url, headers=HEADERS, timeout=20)
        res.raise_for_status()
    except Exception:
        return ""

    soup = BeautifulSoup(res.text, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    body = None
    for selector in [
        "div.se-main-container",
        "div#postViewArea",
        "div.post_ct",
        "div.se_component_wrap",
    ]:
        body = soup.select_one(selector)
        if body:
            break

    if not body:
        return ""

    body_md = md(str(body), heading_style="ATX")
    body_md = re.sub(r"\n{3,}", "\n\n", body_md).strip()

    return body_md


def remove_old_file_for_log_no(log_no, new_path):
    if not log_no:
        return

    for path in glob.glob(os.path.join(POSTS_DIR, f"*{log_no}.md")):
        if path != new_path:
            os.remove(path)


def main():
    feed = feedparser.parse(RSS_URL)

    for entry in feed.entries:
        title = entry.get("title", "Untitled")
        link = entry.get("link", "")

        blog_id, log_no = extract_blog_info(link)
        if not log_no:
            continue

        published = entry.get("published", "")
        if published:
            dt = parsedate_to_datetime(published)
        else:
            dt = datetime.now()

        date_str = dt.strftime("%Y-%m-%d")
        datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S %z")

        slug = slugify(title)
        filename = f"{date_str}-{slug}-{log_no}.md"
        filepath = os.path.join(POSTS_DIR, filename)

        body = fetch_naver_body(link)

        if not body:
            body = entry.get("summary", "")

        original_url = f"https://blog.naver.com/{blog_id}/{log_no}"

        content = f"""---
title: "{escape_yaml(title)}"
date: {datetime_str}
original_url: "{original_url}"
source: "Naver Blog"
log_no: "{log_no}"
---

원문: {original_url}

---

{body}
"""

        remove_old_file_for_log_no(log_no, filepath)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"Synced: {filepath}")

    print("RSS sync complete.")


if __name__ == "__main__":
    main()