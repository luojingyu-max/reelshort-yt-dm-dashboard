#!/usr/bin/env python3
"""
Dailymotion 版:批量频道(user)-> 公开数据(频道维度+视频维度)-> 同款看板 HTML。
复用 yt_report 的看板模板与工具函数,输出字段 schema 与 YouTube 版一致。

公开数据无需认证(普通 API key 都不强制;有 key 限流更高,可放 ~/.dm_key)。

用法:
  python3 dm_report.py x32fdu8 xXXXXXX --out dm_dashboard.html
  python3 dm_report.py --file dm_ids.txt --max 200
"""
import sys, os, json, csv, re, time, urllib.request, urllib.parse, argparse, pathlib, datetime
import yt_report as Y   # 复用 TEMPLATE / fmt_dur / write_csv

API = "https://api.dailymotion.com"

def get(path, **params):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "rs-dm-report/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"error": {"message": "not found"}}
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 * (attempt + 1))   # 限流/瞬时错误 -> 退避重试
                continue
            try: return json.load(e)             # 其它错误返回 JSON 错误体
            except Exception: return {"error": {"message": f"HTTP {e.code}"}}
    return {"error": {"message": "retry exhausted"}}

def iso(ts):
    try: return datetime.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError): return ""

def channel_dim(uid):
    d = get(f"user/{uid}", fields="id,screenname,followers_total,videos_total,views_total,country,created_time")
    if d.get("error"): return None
    return {
        "channel_id": d.get("id"),
        "title": d.get("screenname", ""),
        "country": d.get("country", "") or "",
        "published_at": iso(d.get("created_time")),
        "subscribers": d.get("followers_total"),   # 复用 YouTube 模板的 "订阅" 列 = 粉丝数
        "total_views": d.get("views_total"),
        "videos_total": d.get("videos_total"),
    }

def videos(uid, cap=None):
    rows, page = [], 1
    while True:
        d = get(f"user/{uid}/videos", limit=100, page=page,
                fields="id,title,views_total,likes_total,comments_total,duration,created_time")
        if "list" not in d: return rows
        for v in d.get("list", []):
            sec = int(v.get("duration") or 0)
            rows.append({
                "video_id": v.get("id"),
                "video_title": v.get("title", ""),
                "published_at": iso(v.get("created_time")),
                "duration_sec": sec,
                "duration": Y.fmt_dur(sec),
                "views": v.get("views_total"),
                "likes": v.get("likes_total"),
                "comments": v.get("comments_total"),
                "url": f"https://www.dailymotion.com/video/{v.get('id')}",
            })
            if cap and len(rows) >= cap: return rows
        if not d.get("has_more"): return rows
        page += 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--out", default="dm_dashboard.html")
    a = ap.parse_args()
    ids = list(a.ids)
    if a.file:
        # 直接吃后台导出的表(email + 用户名两列也行):跳过邮箱和中文表头,挑出用户名/ID
        for line in open(a.file):
            for tok in re.split(r"[,\t;\s]+", line.strip()):
                tok = tok.removeprefix("user/")  # 修掉表里多余的 user/ 前缀
                if tok and "@" not in tok and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", tok):
                    ids.append(tok)
    seen = set()
    ids = [x for x in ids if not (x in seen or seen.add(x))]
    if not ids: sys.exit("ERROR: 没有 Dailymotion user id。")

    channels, vids, got = [], [], set()
    for uid in ids:
        c = channel_dim(uid)
        if not c:
            sys.stderr.write(f"[warn] {uid} 无数据/无效,跳过\n"); continue
        if c["channel_id"] in got:
            sys.stderr.write(f"[skip] {uid} 与已抓频道同 ID({c['channel_id']}),别名跳过\n"); continue
        got.add(c["channel_id"])
        channels.append(c)
        vr = videos(uid, a.max)
        for r in vr: r["channel_id"] = c["channel_id"]; r["channel_title"] = c["title"]
        vids += vr
        sys.stderr.write(f"[ok] {c['title']}: 粉丝{c['subscribers']} 总播放{c['total_views']} 视频{len(vr)}/{c['videos_total']}\n")

    Y.write_csv("dm_channels.csv", channels, ["channel_id","title","country","published_at","subscribers","total_views","videos_total"])
    Y.write_csv("dm_videos.csv", vids, ["channel_id","channel_title","video_id","video_title","published_at","duration","duration_sec","views","likes","comments","url"])

    libf = pathlib.Path(Y.__file__).parent / "chart.umd.min.js"
    chartjs = ("<script>"+libf.read_text(encoding="utf-8")+"</script>") if libf.exists() \
              else '<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>'
    html = (Y.TEMPLATE
            .replace("YouTube 频道矩阵看板", "Dailymotion 频道矩阵看板")
            .replace("YouTube Data API v3", "Dailymotion Data API")
            .replace("__CHARTJS__", chartjs)
            .replace("__GEN__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__CH__", json.dumps(channels, ensure_ascii=False))
            .replace("__VID__", json.dumps(vids, ensure_ascii=False)))
    pathlib.Path(a.out).write_text(html, encoding="utf-8")
    sys.stderr.write(f"\n[done] {len(channels)} 频道 / {len(vids)} 视频  ->  dm_channels.csv  dm_videos.csv  {a.out}\n")

if __name__ == "__main__":
    main()
