#!/usr/bin/env python3
"""
生成 BI 底表(供 mapleBI / IT 灌库)。列名 snake_case 英文,UTF-8。
读现有产物:channels.csv, dm_channels.csv, videos.csv, dm_videos.csv,
           history/daily.csv(频道级日快照), history/videos_daily.csv(视频级日快照),
           yt_owners.csv(YT 频道ID->负责人), dm_owners.csv(DM 频道名->负责人)

产出(都在 base_tables/):
  dim_channel.csv      频道维度表(platform, channel_id, channel_name, operator)
  channel_daily.csv    频道级日快照事实表(按天的订阅/总播放)
  video_latest.csv     视频级最新快照事实表(播放/点赞/评论/时长 等全字段)
  video_daily.csv      视频级日快照事实表(按天的累计播放,用于趋势)
"""
import csv, pathlib, sys
HERE = pathlib.Path(__file__).parent
OUT = HERE / "base_tables"; OUT.mkdir(exist_ok=True)

def rd(p):
    p = HERE / p
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []

def wr(name, fields, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    sys.stderr.write(f"[ok] {name}: {len(rows)} 行\n")

# ---- 维度:频道 -> 平台/名称/负责人 ----
yt_own = {r["channel_id"]: r["operator"] for r in rd("yt_owners.csv")}
dm_own = {r["title"].strip(): r["operator"] for r in rd("dm_owners.csv")}
dim = {}   # channel_id -> dict
for r in rd("channels.csv"):
    dim[r["channel_id"]] = {"platform": "YouTube", "channel_id": r["channel_id"],
                            "channel_name": r["title"], "operator": yt_own.get(r["channel_id"], "未分配")}
for r in rd("dm_channels.csv"):
    dim[r["channel_id"]] = {"platform": "Dailymotion", "channel_id": r["channel_id"],
                            "channel_name": r["title"], "operator": dm_own.get(r["title"].strip(), "未分配")}
wr("dim_channel.csv", ["platform", "channel_id", "channel_name", "operator"], list(dim.values()))

def op_of(cid): return dim.get(cid, {}).get("operator", "未分配")
def plat_of(cid): return dim.get(cid, {}).get("platform", "")
def name_of(cid): return dim.get(cid, {}).get("channel_name", "")

# ---- 频道级日快照(time series)----
chd = []
for r in rd("history/daily.csv"):   # date,platform,channel_id,title,total_views,subscribers
    chd.append({"snapshot_date": r["date"], "platform": r["platform"], "operator": op_of(r["channel_id"]),
                "channel_id": r["channel_id"], "channel_name": r["title"],
                "subscribers": r.get("subscribers", ""), "total_views": r.get("total_views", "")})
wr("channel_daily.csv", ["snapshot_date", "platform", "operator", "channel_id", "channel_name",
                         "subscribers", "total_views"], chd)

# ---- 视频级最新快照(full fields)----
vl = []
for plat, src in [("YouTube", "videos.csv"), ("Dailymotion", "dm_videos.csv")]:
    for r in rd(src):
        vl.append({"platform": plat, "operator": op_of(r["channel_id"]),
                   "channel_id": r["channel_id"], "channel_name": r.get("channel_title", ""),
                   "video_id": r["video_id"], "video_title": r["video_title"],
                   "published_date": (r.get("published_at", "") or "")[:10],
                   "duration_sec": r.get("duration_sec", ""), "views": r.get("views", ""),
                   "likes": r.get("likes", ""), "comments": r.get("comments", "")})
wr("video_latest.csv", ["platform", "operator", "channel_id", "channel_name", "video_id",
                        "video_title", "published_date", "duration_sec", "views", "likes", "comments"], vl)

# ---- 视频级日快照(time series:按天累计播放)----
v2c = {r["video_id"]: r["channel_id"] for r in vl}   # video -> channel
vd = []
for r in rd("history/videos_daily.csv"):   # date,video_id,views
    cid = v2c.get(r["video_id"], "")
    vd.append({"snapshot_date": r["date"], "platform": plat_of(cid), "operator": op_of(cid),
               "channel_id": cid, "video_id": r["video_id"], "views": r.get("views", "")})
wr("video_daily.csv", ["snapshot_date", "platform", "operator", "channel_id", "video_id", "views"], vd)

sys.stderr.write("[done] 底表已生成于 base_tables/\n")
