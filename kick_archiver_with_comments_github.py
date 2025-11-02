import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from kick import analyze_comments  # 既存の kick.py 内関数を利用する想定

# === 設定 ===
CHANNEL_ID = "mokoutoaruotoko"
API_URL = f"https://kick.com/api/v2/channels/{CHANNEL_ID}/videos"
ARCHIVE_FILE = "kick_archives.json"
COMMENTS_DIR = "comments"

# 保存ディレクトリ作成
os.makedirs(COMMENTS_DIR, exist_ok=True)


# === ユーティリティ ===
def to_iso(dt_str):
    """Kickのcreated_atをISO形式に統一"""
    if not dt_str:
        return None
    try:
        if "Z" not in dt_str:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc).isoformat()
        return dt_str
    except Exception:
        return None


def format_duration(ms):
    """ミリ秒を HH:MM:SS に整形"""
    try:
        s = int(ms) // 1000
        return time.strftime("%H:%M:%S", time.gmtime(s))
    except Exception:
        return "00:00:00"


# === アーカイブ取得 ===
def fetch_archives(max_retries=3):
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

    for attempt in range(max_retries):
        try:
            req = Request(API_URL, headers=headers)
            with urlopen(req, timeout=15) as response:
                if response.status != 200:
                    print(f"HTTPステータス: {response.status}")
                    continue
                raw = response.read().decode("utf-8")
                data = json.loads(raw)
                return [
                    {
                        "id": v.get("id"),
                        "uuid": v.get("video", {}).get("uuid"),
                        "title": v.get("session_title") or v.get("slug") or "",
                        "created_at": v.get("video", {}).get("created_at"),
                        "url": f"https://kick.com/{CHANNEL_ID}/videos/{v.get('video', {}).get('uuid')}",
                        "duration": v.get("duration"),
                    }
                    for v in data if not v.get("is_live")
                ]

        except HTTPError as e:
            print(f"[{attempt+1}/{max_retries}] HTTPエラー: {e.code}")
            time.sleep(3)
        except URLError as e:
            print(f"[{attempt+1}/{max_retries}] URLエラー: {e.reason}")
            time.sleep(3)
        except Exception as e:
            print(f"[{attempt+1}/{max_retries}] その他のエラー: {e}")
            time.sleep(3)

    print("Kick APIアクセスに失敗しました。")
    return []


# === コメント取得 ===
def get_chat_messages(start_time_iso):
    """指定時刻以降のコメントを取得"""
    start_time_encoded = quote(start_time_iso, safe="")
    headers = {"User-Agent": "Mozilla/5.0"}
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


def get_all_comments(start_time_iso, end_time):
    """配信全体のコメントを取得"""
    all_comments = []
    current = datetime.fromisoformat(start_time_iso)
    current_iso = current.isoformat()

    while current < end_time:
        messages = get_chat_messages(current_iso)
        if not messages:
            current += timedelta(seconds=5)
            current_iso = current.isoformat().replace("+00:00", "Z")
            time.sleep(1)
            continue

        all_comments.extend(messages)
        last_time = messages[-1].get("created_at")
        if not last_time:
            break
        current = datetime.fromisoformat(last_time) + timedelta(seconds=1)
        current_iso = current.isoformat().replace("+00:00", "Z")
        time.sleep(1)

    return all_comments


def save_comment_stats(video, comments):
    """コメント統計を保存（GitHub最適化版）"""
    if not comments:
        print(f"コメントなし: {video['id']}")
        return

    try:
        result = analyze_comments(comments)

        data = {
            "video_id": video["id"],
            "title": video["title"],
            "created_at": video["created_at"],
            "comments_per_minute": [
                {"time": t.isoformat(), "count": int(c)}
                for t, c in zip(result["times"], result["counts"])
            ],
        }

        path = os.path.join("comments", f"{video['id']}_comments.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"コメント統計保存: {path}")

    except Exception as e:
        print(f"統計保存エラー({video['id']}): {e}")



# === メイン ===
def main():
    try:
        # 既存アーカイブ読み込み
        if os.path.exists(ARCHIVE_FILE):
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                local_archives = json.load(f)
        else:
            local_archives = []

        known_ids = {a["id"] for a in local_archives}
        remote_archives = fetch_archives()

        new_archives = [a for a in remote_archives if a["id"] not in known_ids]
        if not new_archives:
            print("新しいアーカイブはありません。")
            return

        for video in new_archives:
            print(f"新しいアーカイブ: {video['title']} ({video['id']})")
            start_time = datetime.fromisoformat(video["created_at"])
            end_time = start_time + timedelta(hours=3)  # 仮の最大長
            comments = get_all_comments(video["created_at"], end_time)
            save_comment_stats(video, comments)
            local_archives.append(video)
            time.sleep(3)

        with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(local_archives, f, ensure_ascii=False, indent=2)
        print("kick_archives.json 更新完了。")

    except Exception as e:
        print(f"実行中エラー: {e}")


if __name__ == "__main__":
    main()
