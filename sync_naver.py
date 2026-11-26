import os
import re
import html
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

RSS_URL = "https://rss.blog.naver.com/ewigenostalgie.xml"
BLOG_ID = "ewigenostalgie"
POSTS_DIR = "_posts"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": f"https://blog.naver.com/{BLOG_ID}",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def clean_text(text):
    if not text:
        return ""
    text = html.unescape(str(text))
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text):
    text = clean_text(text)
    text = re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:80] or "post"


def escape_yaml(text):
    return clean_text(text).replace("\\", "\\\\").replace('"', "'")


def extract_blog_info(url):
    match = re.search(r"(?:https?://)?(?:m\.)?blog\.naver\.com/([^/?#]+)/(\d+)", url)
    if not match:
        return BLOG_ID, None
    return match.group(1), match.group(2)


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

    urls = [
        post_view_url(blog_id, log_no),
        f"https://m.blog.naver.com/{blog_id}/{log_no}",
    ]
    for url in urls:
        try:
            res = requests.get(url, headers=HEADERS, timeout=20)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()

            for selector in [
                "div.se-main-container",
                "div#postViewArea",
                "div.post_ct",
                "div.se_component_wrap",
            ]:
                body = soup.select_one(selector)
                if body is None:
                    continue
                body_md = md(str(body), heading_style="ATX")
                body_md = re.sub(r"\n{3,}", "\n\n", body_md).strip()
                if body_md:
                    return body_md
        except Exception as exc:
            print(f"Fetch failed ({log_no}): {type(exc).__name__}")
    return ""


def existing_posts():
    """Read Naver IDs from front matter, including legacy filenames."""
    posts = {}
    for path in sorted(Path(POSTS_DIR).glob("*.md")):
        content = path.read_text(encoding="utf-8")
        header = content.split("\n---\n", 1)[0]
        match = re.search(
            r'^original_url:\s*["\']?(https?://(?:m\.)?blog\.naver\.com/[^\s"\']+)',
            header,
            re.M,
        )
        if not match:
            continue
        blog_id, log_no = extract_blog_info(match.group(1))
        if blog_id == BLOG_ID and log_no:
            posts.setdefault(log_no, []).append((path, content))
    return posts


def replace_body(content, body):
    """Preserve metadata, original link, date and existing page path."""
    parts = content.split("\n---\n", 2)
    if len(parts) != 3 or not parts[0].startswith("---\n"):
        return None
    if not parts[1].strip().startswith("원문:"):
        return None
    return "\n---\n".join(parts[:2]) + "\n---\n\n" + body + "\n"


def write_if_changed(path, content, previous=None):
    if content == previous:
        return False
    path.write_text(content, encoding="utf-8")
    print(f"Updated: {path}")
    return True


def new_post(entry, log_no, body):
    title = entry.get("title", "Untitled")
    published = entry.get("published", "")
    if not published:
        print(f"Missing publication date; skipped: {log_no}")
        return False
    try:
        dt = parsedate_to_datetime(published)
    except (ValueError, TypeError, OverflowError):
        print(f"Invalid publication date; skipped: {log_no}")
        return False
    date_str = dt.strftime("%Y-%m-%d")
    datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S %z")
    filename = f"{date_str}-{slugify(title)}-{log_no}.md"
    filepath = Path(POSTS_DIR) / filename
    original_url = f"https://blog.naver.com/{BLOG_ID}/{log_no}"
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
    return write_if_changed(filepath, content)


def main():
    Path(POSTS_DIR).mkdir(parents=True, exist_ok=True)
    posts = existing_posts()
    feed = feedparser.parse(RSS_URL)
    recent = {}
    for entry in feed.entries:
        blog_id, log_no = extract_blog_info(entry.get("link", ""))
        if blog_id == BLOG_ID and log_no:
            recent[log_no] = entry

    if not recent:
        print("WARNING: RSS returned no usable entries.")

    # Recent RSS entries are fetched every run; the full archive is fetched
    # once per Korean calendar day and whenever the workflow is run manually.
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    state = Path(POSTS_DIR) / ".naver-last-full-refresh"
    last_full = state.read_text(encoding="utf-8").strip() if state.exists() else ""
    full = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" or last_full != today
    targets = list(recent)
    if full:
        targets += [log_no for log_no in posts if log_no not in recent]

    print(f"Mode: {'full archive' if full else 'recent RSS'}; targets: {len(targets)}")
    updated = failed = fetched = 0

    def fetch(log_no):
        return fetch_naver_body(f"https://blog.naver.com/{BLOG_ID}/{log_no}")

    with ThreadPoolExecutor(max_workers=3) as executor:
        for log_no, body in zip(targets, executor.map(fetch, targets)):
            if not body:
                failed += 1
                print(f"WARNING: No original body for {log_no}; existing content kept.")
                continue
            fetched += 1
            if log_no in posts:
                for path, previous in posts[log_no]:
                    content = replace_body(previous, body)
                    if content is None:
                        failed += 1
                        print(f"WARNING: Unrecognized archive format; kept {path}")
                        continue
                    # RSS titles may change; retain the existing filename.
                    if log_no in recent and recent[log_no].get("title"):
                        title = escape_yaml(recent[log_no]["title"])
                        header, rest = content.split("\n---\n", 1)
                        header = re.sub(
                            r"(?m)^title:.*$", lambda _: f'title: "{title}"', header, count=1
                        )
                        content = header + "\n---\n" + rest
                    updated += int(write_if_changed(path, content, previous))
            elif log_no in recent:
                updated += int(new_post(recent[log_no], log_no, body))

    # Record a daily attempt, not a claim that all posts were accessible.
    # If every fetch failed, retain the marker so the next run can retry.
    if full and fetched and last_full != today:
        state.write_text(today + "\n", encoding="utf-8")

    print(f"Sync complete: {len(targets)} targets, {fetched} fetched, {updated} changed, {failed} failures.")
    if (targets and not fetched) or (not targets and not recent):
        raise SystemExit("No original bodies fetched; retry required.")


if __name__ == "__main__":
    main()