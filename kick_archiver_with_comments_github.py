import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote
import sys
import functools

# すべての print() を stderr に出す
print = functools.partial(print, file=sys.stderr, flush=True)

# === ユーザーが指定する基準日時（ここを変更してください） ===
USER_START_DATE = "2025-11-06T00:00:00+09:00"

# === 設定 ===
CHANNEL_ID = "56495977"
CHANNEL_NAME = "mokoutoaruotoko"
API_URL = f"https://kick.com/api/v2/channels/{CHANNEL_NAME}/videos"
# 動画一覧ページ (v7 uuid の取得元。下の fetch_v7_map を参照)
VIDEOS_PAGE_URL = f"https://kick.com/{CHANNEL_NAME}/videos"
# 保存フォルダ設定
COMMENTS_GITHUB = "comments_github"
COMMENTS_LOCAL = "comments_local"
ARCHIVE_FILE = "kick_archives.json"
os.makedirs(COMMENTS_GITHUB, exist_ok=True)
os.makedirs(COMMENTS_LOCAL, exist_ok=True)

def get_comment_dir():
    """実行環境に応じて保存フォルダを決定"""
    # GitHub Actions 環境変数がセットされている場合 → GitHub用
    if os.getenv("GITHUB_ACTIONS") == "true":
        return COMMENTS_GITHUB
    # ローカル実行なら comments_local に保存
    return COMMENTS_LOCAL

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


# === v7 uuid の解決 ===
# Kick は動画ページURLの識別子を v4 uuid から v7 uuid へ移行したが、レガシーAPI(API_URL)は
# 今も v4 の video.uuid しか返さない。v4 のURLは現在 404 になるため、そのまま保存すると
# リンク切れになる。v7 の先頭48bitは start_time(ms) だが残りは乱数なので計算では復元できない。
# そこで動画一覧ページに埋め込まれたSSRデータ(v7を "id" として持つ)から
# start_time -> v7 uuid の対応表を作り、URL生成時に差し替える。
V7_ID_RE = re.compile(r'"id":"([0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})"')
START_TIME_RE = re.compile(r'"start_time":"([^"]+)"')


def to_epoch(dt_str):
    """ISO文字列を epoch 秒(int)に変換。失敗時は None。"""
    if not dt_str:
        return None
    try:
        s = dt_str.replace(" ", "T")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def fetch_v7_map():
    """動画一覧ページから {start_time(epoch秒): v7 uuid} を取得する。

    取得や解析に失敗した場合は空 dict を返す。呼び出し側は従来通り v4 uuid を使うため、
    (リンクは直らないが) 収集処理自体は止まらない。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://kick.com/",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = Request(VIDEOS_PAGE_URL, headers=headers)
        with urlopen(req, timeout=25) as res:
            html = res.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"v7対応表の取得に失敗（従来のuuidを使用）: {e}")
        return {}

    # RSCペイロード内のJSONはエスケープされて埋め込まれている
    text = html.replace('\\"', '"')
    v7_map = {}
    for m in V7_ID_RE.finditer(text):
        # キーはアルファベット順で並ぶため start_time は id の後方にある
        window = text[m.end():m.end() + 2500]
        s = START_TIME_RE.search(window)
        if not s:
            continue
        key = to_epoch(s.group(1))
        if key is not None:
            v7_map.setdefault(key, m.group(1))

    print(f"v7 uuid 対応表: {len(v7_map)} 件取得")
    return v7_map


def resolve_uuid(v7_map, start_time_iso, fallback=None):
    """start_time から v7 uuid を引く。見つからなければ fallback を返す。"""
    key = to_epoch(start_time_iso)
    if key is None:
        return fallback
    for k in (key, key - 1, key + 1):  # 秒の丸め差を許容
        if k in v7_map:
            return v7_map[k]
    return fallback


def build_video_url(uuid):
    return f"https://kick.com/{CHANNEL_NAME}/videos/{uuid}"


def backfill_urls(archives, v7_map):
    """既存エントリのURLを v7 uuid に貼り替える。

    Kick は一定期間で古い動画を削除する(=一覧に出ない)ため、対応表に無いものは
    そもそも視聴可能なURLが存在しない。その場合は変更しない。
    """
    fixed = 0
    for a in archives:
        new_uuid = resolve_uuid(v7_map, a.get("start_time"))
        if not new_uuid:
            continue
        new_url = build_video_url(new_uuid)
        if a.get("url") != new_url:
            a["url"] = new_url
            fixed += 1
    if fixed:
        print(f"🔧 既存エントリのURLを v7 に修正: {fixed} 件")
    return fixed


def mark_availability(archives, v7_map):
    """各エントリに available (Kick上に動画が残っているか) を付与する。

    Kick は一定期間で古いVODを削除するため、一覧に無い動画はもう視聴できない
    (URLをどう組み立ててもリンク切れになる)。まとめサイト側はこのフラグを見て
    リンクを無効化し「削除済み」と表示する。

    誤判定を避けるためのガード:
      - 対応表が空(一覧の取得失敗)なら何もしない。全件を削除済みにしてしまわないため。
      - 対応表の最古より新しいのに一覧に無いものは判定を保留する。取りこぼし対策。
    """
    if not v7_map:
        return 0

    oldest = min(v7_map)
    changed = 0
    for a in archives:
        if resolve_uuid(v7_map, a.get("start_time")):
            value = True
        else:
            ts = to_epoch(a.get("start_time"))
            if ts is None or ts >= oldest:
                continue  # 判定保留
            value = False  # 保持期間より古い = 確実に削除済み
        if a.get("available") != value:
            a["available"] = value
            changed += 1

    if changed:
        gone = sum(1 for a in archives if a.get("available") is False)
        print(f"🏷️ available を更新: {changed} 件 (削除済み合計 {gone} 件)")
    return changed


# === アーカイブ取得 ===
def fetch_archives(v7_map=None, max_retries=3):
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

    v7_map = v7_map or {}

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
                    # URLには v7 uuid を使う (無ければ従来の v4 にフォールバック)
                    uuid_v4 = v.get("video", {}).get("uuid")
                    formatted.append({
                        "id": v.get("id"),
                        "video_id": v.get("video", {}).get("id"),
                        "uuid": uuid_v4,
                        "title": v.get("session_title") or "",
                        "start_time": t,
                        "url": build_video_url(resolve_uuid(v7_map, t, uuid_v4)),
                        "duration": v.get("duration"),
                        "video_length":format_duration(v.get("duration")),
                        "available": True,  # 一覧に載っている = 視聴可能
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
    limit = datetime.now(timezone.utc) - timedelta(days=30)

    for el in os.listdir(COMMENTS_GITHUB):
        if not el.endswith("_comments.json"):
            continue
        
        path = os.path.join(COMMENTS_GITHUB, el)        
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)

        created = obj.get('start_time')
        if created:
            ctime = datetime.fromisoformat(created)
            if ctime < limit:
                os.remove(path)
                print(f"🧹 古いコメント削除: {el}")



# === メイン ===
def main():
    try:
        print("Fetching archive list...")
        local_archives = load_local_archives()
        known_ids = {a["id"] for a in local_archives}
        v7_map = fetch_v7_map()
        remote_archives = fetch_archives(v7_map)

        new_archives = [a for a in remote_archives if a["id"] not in known_ids]
        if not new_archives:
            print("新しいアーカイブはありません。")

        for video in new_archives:
            print(f"新しいアーカイブ: {video['title']} ({video['id']})")
            start_time_iso, start_time_dt, end_time_dt = compute_timeinfo(video)
            comments = get_all_comments(start_time_iso, start_time_dt, end_time_dt)
            video['number_of_comments'] = len(comments)
            save_comment_stats(video, comments)
            local_archives.append(video)
            time.sleep(3)
            if(video==new_archives[-1]): update_archive_data(local_archives)

        # 既存エントリのURLを v4 → v7 に貼り替え、視聴可否フラグを更新する
        touched = backfill_urls(local_archives, v7_map)
        touched += mark_availability(local_archives, v7_map)
        if touched:
            update_archive_data(local_archives)

        cleanup_old_comments()

    except Exception as e:
        print(f"実行中エラー: {e}")


if __name__ == "__main__":
    main()
