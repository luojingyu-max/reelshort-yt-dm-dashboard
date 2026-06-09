#!/usr/bin/env python3
"""
每日快照:把当前各频道的累计总播放/订阅追加进 history/daily.csv。
- 读 channels.csv(YouTube)+ dm_channels.csv(Dailymotion)。
- 每天一行/频道;同一天重跑会覆盖当天(按 date+platform+channel_id 去重)。
- 历史无法从 API 回填,只能逐日累积。
"""
import csv, datetime, pathlib, sys

HERE = pathlib.Path(__file__).parent
HIST = HERE / "history" / "daily.csv"
VHIST = HERE / "history" / "videos_daily.csv"
FIELDS = ["date", "platform", "channel_id", "title", "total_views", "subscribers"]
VFIELDS = ["date", "video_id", "views"]
VKEEP_DAYS = 90   # 视频级快照体积大,只保留近 90 天

def load(path, platform):
    p = HERE / path
    if not p.exists(): return []
    out = []
    for r in csv.DictReader(open(p)):
        out.append({"platform": platform, "channel_id": r["channel_id"], "title": r["title"],
                    "total_views": r.get("total_views", ""), "subscribers": r.get("subscribers", "")})
    return out

def load_videos(path):
    p = HERE / path
    if not p.exists(): return []
    return [{"video_id": r["video_id"], "views": r.get("views", "")} for r in csv.DictReader(open(p))]

def snap_videos(today):
    rows = load_videos("videos.csv") + load_videos("dm_videos.csv")
    for r in rows: r["date"] = today
    existing = []
    if VHIST.exists():
        existing = [r for r in csv.DictReader(open(VHIST)) if r["date"] != today]
    merged = existing + rows
    cutoff = (datetime.date.today() - datetime.timedelta(days=VKEEP_DAYS)).isoformat()
    merged = [r for r in merged if r["date"] >= cutoff]   # 裁剪到近 90 天
    with open(VHIST, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=VFIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(merged)
    sys.stderr.write(f"[snapshot] 视频级:追加 {len(rows)} 条;videos_daily.csv 现 {len(merged)} 行\n")

def main():
    today = datetime.date.today().isoformat()
    rows = load("channels.csv", "YouTube") + load("dm_channels.csv", "Dailymotion")
    for r in rows: r["date"] = today

    HIST.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if HIST.exists():
        existing = [r for r in csv.DictReader(open(HIST)) if r["date"] != today]  # 去掉今天的旧快照
    merged = existing + rows
    with open(HIST, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader(); w.writerows(merged)
    days = len({r["date"] for r in merged})
    sys.stderr.write(f"[snapshot] {today}: 追加 {len(rows)} 频道;history/daily.csv 现含 {days} 天 / {len(merged)} 行\n")
    snap_videos(today)

if __name__ == "__main__":
    main()
