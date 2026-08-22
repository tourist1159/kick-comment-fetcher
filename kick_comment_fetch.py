"""
kick_archives.json 内で number_of_comments が未設定(=kick_meta_fetch.py がメタだけ
先に登録した未処理エントリ)のものを対象に、チャットを取得して集計する。

メタ取得(kick_meta_fetch.py)とはコミットを分けている。メタだけ先に push すること
でタイムライン側にタイトル・サムネ・日時をすぐ反映でき、コメント集計(配信が長いと
数分かかる)を待つ必要が無くなる。
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote
import sys
import functools

print = functools.partial(print, file=sys.stderr, flush=True)

CHANNEL_ID = "56495977"
COMMENTS_GITHUB = "comments_github"
COMMENTS_LOCAL = "comments_local"
ARCHIVE_FILE = "kick_archives.json"
os.makedirs(COMMENTS_GITHUB, exist_ok=True)
os.makedirs(COMMENTS_LOCAL, exist_ok=True)


def get_comment_dir():
    """実行環境に応じて保存フォルダを決定"""
    if os.getenv("GITHUB_ACTIONS") == "true":
        return COMMENTS_GITHUB
    return COMMENTS_LOCAL


def compute_timeinfo(video):
    start_time_iso = video["start_time"]
    start_time_dt = datetime.fromisoformat(start_time_iso)
    duration = video["duration"]
    end_time_dt = start_time_dt + timedelta(milliseconds=duration)
    return start_time_iso, start_time_dt, end_time_dt


def get_chat_messages(start_time_iso):
    """指定時刻以降のコメントを取得"""
    start_time_encoded = quote(start_time_iso, safe="")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://kick.com/",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }
    url = f"https://kick.com/api/v2/channels/{CHANNEL_ID}/messages?start_time={start_time_encoded}"

    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
            return data.get("data", {}).get("messages", [])
    except HTTPError as e:
        print(f"HTTPエラー: {e.code} {url}")
    except URLError as e:
        print(f"URLエラー: {e.reason}")
    except Exception as e:
        print(f"コメント取得エラー: {e}")
    return []


def get_all_comments(start_time_iso, start_time, end_time):
    """配信全体のコメントを取得"""
    all_comments = []
    current = start_time
    current_iso = start_time_iso

    while current < end_time:
        print(f"取得中: {current}/{end_time}")
        messages = get_chat_messages(current_iso)
        if not messages:
            current += timedelta(seconds=5)
            current_iso = current.isoformat()
            time.sleep(1)
            continue

        for msg in messages:
            all_comments.append({
                "id": msg["user_id"],
                "timestamp": msg.get("created_at"),
                "text": msg.get("content") or "",
            })

        last_time = messages[-1].get("created_at")
        if not last_time:
            break
        current = datetime.fromisoformat(last_time) + timedelta(seconds=1)
        current_iso = current.isoformat()
        time.sleep(1)

    return all_comments


def save_comment_stats(video, comments):
    comment_dir = get_comment_dir()
    if not comments:
        print(f"コメントなし: {video['id']}")
        return

    try:
        data = {
            "video_id": video["id"],
            "start_time": video["start_time"],
            "video_length": video["video_length"],
            "number_of_comments": video["number_of_comments"],
            "comments": comments,
        }
        path = os.path.join(comment_dir, f"{video['id']}_comments.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"コメント統計保存: {path}")
    except Exception as e:
        print(f"統計保存エラー({video['id']}): {e}")


def load_local_archives():
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def update_archive_data(archives):
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archives, f, ensure_ascii=False, indent=2)
    print(f"📁 {ARCHIVE_FILE} 更新完了")


def cleanup_old_comments():
    """古いコメントを削除（GitHubフォルダのみ）"""
    limit = datetime.now(timezone.utc) - timedelta(days=30)
    for el in os.listdir(COMMENTS_GITHUB):
        if not el.endswith("_comments.json"):
            continue
        path = os.path.join(COMMENTS_GITHUB, el)
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        created = obj.get("start_time")
        if created:
            ctime = datetime.fromisoformat(created)
            if ctime < limit:
                os.remove(path)
                print(f"🧹 古いコメント削除: {el}")


def main():
    try:
        local_archives = load_local_archives()
        pending = [a for a in local_archives if "number_of_comments" not in a]

        if not pending:
            print("処理待ちのアーカイブはありません。")
        else:
            print(f"処理待ち: {len(pending)} 件")

        for video in pending:
            print(f"コメント取得: {video['title']} ({video['id']})")
            start_time_iso, start_time_dt, end_time_dt = compute_timeinfo(video)
            comments = get_all_comments(start_time_iso, start_time_dt, end_time_dt)
            video["number_of_comments"] = len(comments)
            save_comment_stats(video, comments)
            update_archive_data(local_archives)  # 1件ごとに保存 (途中で落ちても取りこぼしを減らす)
            time.sleep(3)

        cleanup_old_comments()

    except Exception as e:
        print(f"実行中エラー: {e}")


if __name__ == "__main__":
    main()
