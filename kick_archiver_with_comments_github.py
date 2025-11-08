import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote
import sys
import functools
from pprint import pprint

# すべての print() を stderr に出す
print = functools.partial(print, file=sys.stderr, flush=True)

# === ユーザーが指定する基準日時（ここを変更してください） ===
USER_START_DATE = "2025-11-06T00:00:00+09:00"

# === 設定 ===
CHANNEL_ID = "56495977"
CHANNEL_NAME = "mokoutoaruotoko"
API_URL = f"https://kick.com/api/v2/channels/{CHANNEL_NAME}/videos"
# 保存フォルダ設定
COMMENTS_GITHUB = "comments_github"
COMMENTS_LOCAL = "comments_local"
ARCHIVE_FILE = "kick_archives.json"

# ローカル優先
def get_comment_dir():
    return COMMENTS_LOCAL if os.path.exists(COMMENTS_LOCAL) else COMMENTS_GITHUB

# === ユーティリティ ===
def to_iso(dt_str):
    """Kickのcreated_atをISO形式に統一"""
    if not dt_str:
        return None
    try:
        newdt = dt_str.replace(" ", "T")
        if (not "Z" in newdt ): newdt = newdt+"Z"
        return datetime.fromisoformat(newdt).isoformat()
    except Exception:
        return None


def format_duration(ms):
    """ミリ秒を HH:MM:SS に整形"""
    try:
        s = int(ms) // 1000
        return time.strftime("%H:%M:%S", time.gmtime(s))
    except Exception:
        return "00:00:00"
    
    
def compute_timeinfo(video):
    start_time_iso = video["start_time"]
    start_time_dt = datetime.fromisoformat(start_time_iso)
    duration = video["duration"]
    end_time_dt = start_time_dt + timedelta(milliseconds=duration)
    return start_time_iso, start_time_dt, end_time_dt


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
                formatted = []
                # ユーザーが指定した基準日時を UTC に変換        
                user_start_dt = datetime.fromisoformat(USER_START_DATE).astimezone(timezone.utc)    
                for v in data:
                    if v.get("is_live"): continue
                    t = to_iso(v.get("start_time"))
                    # 指定日時以降のアーカイブのみ対象
                    if datetime.fromisoformat(t) < user_start_dt: continue
                    formatted.append({
                        "id": v.get("id"),
                        "video_id": v.get("video", {}).get("id"),
                        "uuid": v.get("video", {}).get("uuid"),
                        "title": v.get("session_title") or "",
                        "start_time": t,
                        "url": f"https://kick.com/{CHANNEL_NAME}/videos/{v.get('video', {}).get('uuid')}",
                        "duration": v.get("duration"),
                        "video_length":format_duration(v.get("duration")),
                    })
                return formatted

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

# ---------- ローカル保存管理 ----------
def load_local_archives():
    if os.path.exists(ARCHIVE_FILE):
        with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

# === コメント取得 ===
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
            msg = data.get("data", {}).get("messages", [])
            return msg
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
            id=msg['user_id']
            t=msg.get('created_at')
            c=msg.get('content') or ''
            all_comments.append({"id": id, "timestamp": t, "text": c})
            
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
        
# kick_archives.jsonを更新
def update_archive_data(archives):
    with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(archives, f, ensure_ascii=False, indent=2)
    print(f"📁 {ARCHIVE_FILE} 更新完了")

# 古いコメントを削除（GitHubフォルダのみ）
def cleanup_old_comments():
    limit = datetime.now(timezone.utc) - timedelta(days=7)
    for f in os.listdir(COMMENTS_GITHUB):
        if not f.endswith("_comments.json"):
            continue
        path = os.path.join(COMMENTS_GITHUB, f)
        mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
        if mtime < limit:
            os.remove(path)
            print(f"🧹 古いコメント削除: {f}")



# === メイン ===
def main():
    try:
        print("Fetching archive list...")
        local_archives = load_local_archives()
        known_ids = {a["id"] for a in local_archives}
        remote_archives = fetch_archives()    

        new_archives = [a for a in remote_archives if a["id"] not in known_ids]
        if not new_archives:
            print("新しいアーカイブはありません。")
            return

        for video in new_archives:
            print(f"新しいアーカイブ: {video['title']} ({video['id']})")
            start_time_iso, start_time_dt, end_time_dt = compute_timeinfo(video)
            comments = get_all_comments(start_time_iso, start_time_dt, end_time_dt)
            video['number_of_comments'] = len(comments)
            save_comment_stats(video, comments)
            local_archives.append(video)
            time.sleep(3)

        update_archive_data(local_archives)
        
        cleanup_old_comments()

    except Exception as e:
        print(f"実行中エラー: {e}")


if __name__ == "__main__":
    main()
