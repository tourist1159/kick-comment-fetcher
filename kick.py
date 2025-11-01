import json
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime, timedelta,time as timestr, timezone
from collections import defaultdict
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import time
import re
from urllib.parse import quote

CHANNEL_ID = "56495977"  # ← ここを実際のチャンネルIDに置き換えてください

def calc_end_time(start_time_iso, video_len):
    pattern=r'\d{2}:\d{2}:\d{2}'
    repatter=re.compile(pattern)
    if (not repatter.match(video_len)):
        video_len="00:"+video_len
    t1=datetime.fromisoformat(start_time_iso)
    t2=timestr.fromisoformat(video_len)
    td=timedelta(hours=t2.hour, minutes=t2.minute, seconds=t2.second)
    t3=t1+td
    t4=t3.isoformat().replace("+00:00", "Z")
    
    return t3


def get_chat_messages(start_time_iso):
    start_time_encoded=quote(start_time_iso, safe="")
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://kick.com/api/v2/channels/{CHANNEL_ID}/messages?start_time={start_time_encoded}"
    req = Request(url, headers=headers)

    try:
        with urlopen(req) as response:
            raw = response.read()
            data = json.loads(raw.decode("utf-8"))
            messages = data.get("data", {}).get("messages", [])
            return messages
    except HTTPError as e:
        print(f"HTTPエラー: {e.code}")
    except URLError as e:
        print(f"URLエラー: {e.reason}")
    except Exception as e:
        print(f"その他のエラー: {e}")

    return []

def get_all_comments(start_time_iso, end_time):
    all_comments = []
    current_time_iso = start_time_iso
    current_time = datetime.fromisoformat(current_time_iso)

    while (current_time < end_time):
        print(f"取得中: {current_time}/{end_time}")
        messages = get_chat_messages(current_time_iso)
  
        if not messages:
            current_time=current_time+timedelta(seconds=5)
            current_time_iso=current_time.isoformat().replace("+00:00", "Z")
            time.sleep(1)
            continue

        all_comments.extend(messages)

        # 最後のコメントの時間を次の開始時刻にする（+1秒で重複回避）
        last_time = messages[-1]["created_at"]
        current_time = datetime.fromisoformat(last_time) + timedelta(seconds=1)
        current_time_iso=current_time.isoformat().replace("+00:00", "Z")

        time.sleep(1)

    return all_comments

def is_NGpattern(user_id, dt, content, commentlog):
    NG_time_interval = timedelta(seconds=10)
    pattern = re.compile(r'^(\[emote:(\d+):(\w+)\])+$')
    if (pattern.match(content)): return True
    if (len(commentlog)):
        for data in commentlog:
            if (data['id'] == user_id):
                if (data['content'] == content or dt - data['time'] < NG_time_interval): return True
    
    return False

def aggregate_comments_by_minute(comments):
    comment_times = defaultdict(int)
    commentlog = []
    for c in comments:
        user_id = c.get('user_id')
        timestamp = c.get('created_at')
        content = c.get("content")
        if timestamp:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            dt2 = dt.replace(second=0, microsecond=0)
            if (is_NGpattern(user_id, dt, content, commentlog) == False): 
                comment_times[dt2] += 1
                
            commentdata = {'id':user_id, 'time':dt, 'content':content}
            commentlog.append(commentdata)
            if(len(commentlog)>50): commentlog.pop(0)

    df = pd.DataFrame(list(comment_times.items()), columns=["time", "count"])
    df.sort_values("time", inplace=True)
    df.set_index("time", inplace=True)
    return df

def plot_comment_flow(df):
    plt.figure(figsize=(12, 6))
    df["count"].plot(kind="line")
    plt.title("Kick コメント流量（1分ごと）")
    plt.xlabel("時間")
    plt.ylabel("コメント数")
    plt.grid(True)
    plt.tight_layout()
    plt.show()
    
def analyze_comments(comments):
    """
    コメント配列を解析し、「1分あたりのコメント数」を返す。
    pandas なし、GitHub Actions 向け軽量設計。
    
    Parameters:
      comments: list of dicts
        例: [{"timestamp": "2025-10-20T16:12:46+00:00", "id": 123, "text": "かわいい"}, ...]

    Returns:
      dict: {"times": [datetime, ...], "counts": [int, ...]}
    """

    # Kick API形式対応（created_atでもtimestampでも対応）
    timestamps = []
    for c in comments:
        t = c.get("timestamp") or c.get("created_at")
        if not t:
            continue
        try:
            timestamps.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
        except Exception:
            continue

    if not timestamps:
        return {"times": [], "counts": []}

    timestamps.sort()
    start_time = timestamps[0]
    end_time = timestamps[-1]

    # 1分単位で初期化
    comment_bins = defaultdict(int)
    for t in timestamps:
        offset_min = int((t - start_time).total_seconds() // 60)
        comment_bins[offset_min] += 1

    # 等間隔の時系列データに変換
    times = []
    counts = []
    total_minutes = int((end_time - start_time).total_seconds() // 60) + 1

    for i in range(total_minutes):
        times.append(start_time + timedelta(minutes=i))
        counts.append(comment_bins.get(i, 0))

    return {"times": times, "counts": counts}    

def main():
    print("Kickからチャット取得開始...")
    start_time, end_time=input("start_time, end_time:")
    comments = get_all_comments(start_time, end_time)
    print(f"総コメント数: {len(comments)}")

    if not comments:
        print("コメントが取得できませんでした。")
        return

    df = aggregate_comments_by_minute(comments)
    plot_comment_flow(df)

if __name__ == "__main__":
    main()
