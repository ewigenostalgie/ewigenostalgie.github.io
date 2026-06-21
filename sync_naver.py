import os
import re
import json
import time
import html
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from datetime import datetime, timezone, timedelta

BLOG_ID = "ewigenostalgie"
POSTS_DIR = "_posts"
COUNT_PER_PAGE = 30
MAX_PAGES = 300

os.makedirs(POSTS_DIR, exist_ok=True)

KST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": f"https://blog.naver.com/{BLOG_ID}",
}


def clean_text(text):
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r"<.*?>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def slugify(text):
    text = clean_text(text)
    text = re.sub(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:80] or "post"


def escape_yaml(text):
    return clean_text(text).replace("\\", "\\\\").replace('"', "'")


def parse_korean_date(text):
    """
    가능한 형식:
    2026. 4. 18. 21:54
    2026.04.18.
    2026-04-18 21:54
    """
    if not text:
        return None

    text = clean_text(text)

    m = re.search(
        r"(\d{4})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})"
        r"(?:[.\s일]*(\d{1,2})[:시]\s*(\d{1,2}))?",
        text,
    )

    if not m:
        return None

    year = int(m.group(1))
    month = int(m.group(2))
    day = int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)

    return datetime(year, month, day, hour, minute, tzinfo=KST)


def post_list_url(page):
    return (
        "https://blog.naver.com/PostTitleListAsync.naver"
        f"?blogId={BLOG_ID}"
        f"&currentPage={page}"
        f"&countPerPage={COUNT_PER_PAGE}"
        "&categoryNo="
    )


def parse_post_list_response(text):
    """
    네이버 응답 형식이 바뀔 수 있어서:
    1차: JSON으로 파싱
    2차: 정규식으로 logNo만 추출
    """
    posts = []

    # 1차: JSON 파싱 시도
    try:
        data = json.loads(text)
        raw_posts = data.get("postList", []) or data.get("result", {}).get("postList", [])
        for item in raw_posts:
            log_no = str(item.get("logNo") or item.get("logNoStr") or "").strip()
            if not log_no:
                continue

            title = clean_text(item.get("title") or item.get("postTitle") or "")
            date_raw = (
                item.get("addDate")
                or item.get("addDateTime")
                or item.get("postAddDate")
                or item.get("date")
                or ""
            )

            posts.append(
                {
                    "log_no": log_no,
                    "title": title,
                    "date_raw": date_raw,
                }
            )

        if posts:
            return posts
    except Exception:
        pass

    # 2차: 정규식으로 logNo 추출
    log_nos = re.findall(r'"?logNo"?\s*:\s*"?(\d+)"?', text)
    seen = set()

    for log_no in log_nos:
        if log_no in seen:
            continue
        seen.add(log_no)
        posts.append(
            {
                "log_no": log_no,
                "title": "",
                "date_raw": "",
            }
        )

    return posts


def collect_all_posts():
    all_posts = []
    seen = set()

    for page in range(1, MAX_PAGES + 1):
        url = post_list_url(page)
        print(f"Fetching list page {page}: {url}")

        res = requests.get(url, headers=HEADERS, timeout=20)
        res.raise_for_status()

        posts = parse_post_list_response(res.text)

        new_count = 0
        for post in posts:
            log_no = post["log_no"]
            if log_no in seen:
                continue

            seen.add(log_no)
            all_posts.append(post)
            new_count += 1

        print(f"Page {page}: {new_count} new posts")

        if new_count == 0:
            break

        time.sleep(0.4)

    return all_posts


def post_view_url(log_no):
    return (
        "https://blog.naver.com/PostView.naver"
        f"?blogId={BLOG_ID}"
        f"&logNo={log_no}"
        "&redirect=Dlog"
        "&widgetTypeCall=true"
        "&directAccess=false"
    )


def extract_post(log_no, fallback_title="", fallback_date_raw=""):
    url = post_view_url(log_no)
    print(f"Fetching post {log_no}: {url}")

    res = requests.get(url, headers=HEADERS, timeout=25)
    res.raise_for_status()

    soup = BeautifulSoup(res.text, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    # 제목 추출
    title = fallback_title

    title_selectors = [
        "div.se-title-text span",
        "span.se-fs-",
        "h3.se_textarea",
        "meta[property='og:title']",
        "title",
    ]

    if not title:
        og = soup.select_one("meta[property='og:title']")
        if og and og.get("content"):
            title = og.get("content")

    if not title:
        title_tag = soup.select_one("title")
        if title_tag:
            title = title_tag.get_text(" ", strip=True)

    title = clean_text(title).replace(" : 네이버 블로그", "")
    if not title:
        title = f"naver-post-{log_no}"

    # 날짜 추출
    date_candidates = [fallback_date_raw]

    for selector in [
        "span.se_publishDate",
        "p.blog_date",
        "span.date",
        "p.date",
        ".se_publishDate",
        ".blog2_container .date",
    ]:
        el = soup.select_one(selector)
        if el:
            date_candidates.append(el.get_text(" ", strip=True))

    dt = None
    for candidate in date_candidates:
        dt = parse_korean_date(candidate)
        if dt:
            break

    if not dt:
        dt = datetime.now(KST)

    # 본문 추출
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

    if body:
        body_md = md(str(body), heading_style="ATX")
        body_md = re.sub(r"\n{3,}", "\n\n", body_md).strip()
    else:
        body_md = ""

    original_url = f"https://blog.naver.com/{BLOG_ID}/{log_no}"

    return {
        "log_no": log_no,
        "title": title,
        "date": dt,
        "body": body_md,
        "original_url": original_url,
    }


def write_post(post):
    dt = post["date"]
    date_str = dt.strftime("%Y-%m-%d")
    datetime_str = dt.strftime("%Y-%m-%d %H:%M:%S %z")

    slug = slugify(post["title"])
    filename = f"{date_str}-{slug}-{post['log_no']}.md"
    filepath = os.path.join(POSTS_DIR, filename)

    content = f"""---
title: "{escape_yaml(post['title'])}"
date: {datetime_str}
original_url: "{post['original_url']}"
source: "Naver Blog"
log_no: "{post['log_no']}"
---

원문: {post['original_url']}

---

{post['body']}
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Written: {filepath}")


def main():
    posts = collect_all_posts()
    print(f"Collected {len(posts)} posts")

    for item in posts:
        try:
            post = extract_post(
                item["log_no"],
                fallback_title=item.get("title", ""),
                fallback_date_raw=item.get("date_raw", ""),
            )
            write_post(post)
            time.sleep(0.5)
        except Exception as e:
            print(f"Failed post {item.get('log_no')}: {e}")

    print("Full sync complete.")


if __name__ == "__main__":
    main()