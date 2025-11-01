
from datetime import datetime, timedelta
from collections import defaultdict

CHANNEL_ID = "56495977"  # ← ここを実際のチャンネルIDに置き換えてください

 
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
