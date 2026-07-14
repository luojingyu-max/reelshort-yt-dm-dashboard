#!/usr/bin/env python3
"""
拉取 YouTube 视频维度数据(服务端 videoRevenue 接口)-> 聚合成两份小 CSV:
  1) channel_metrics_daily.csv  频道×天聚合
  2) video_summary.csv          每视频在窗口内的汇总

视频×天原始数据量巨大,不落原始、不入库,只存聚合结果。默认近 N 天滚动(--days),覆盖写。

接口返回 collections[] = {video_id,date,channel_id,views,likes,comments,shares,
  average_view_percentage,average_view_duration,estimated_revenue,subscribers_gained,currency}

⚠️ 已知:服务端 `views` 字段当前不可靠(常 0 却有点赞/收益),已反馈排查。
  完播率/观看时长的聚合做成稳健:窗口内有 views 则按播放加权,否则退化成简单平均。
  RPM/互动率(依赖 views)暂不由看板展示,等 views 修好。

token 从环境变量 REVENUE_API_TOKEN 读取。
"""
import sys, os, csv, json, time, argparse, pathlib, datetime
import urllib.request, urllib.parse, urllib.error

API = "http://v-adm-api.stardustgod.com/api/youtube/videoRevenue"
HERE = pathlib.Path(__file__).parent

def get_token(cli):
    t = cli or os.environ.get("REVENUE_API_TOKEN")
    if not t: sys.exit("ERROR: 没有 token (设 REVENUE_API_TOKEN 或 --token)。")
    return t.strip()

def fetch_page(token, start, end, channel_ids, page, page_size=100, retries=5):
    q = {"token": token, "start_date": start, "end_date": end, "page": page, "page_size": page_size}
    if channel_ids: q["channel_ids"] = channel_ids
    url = f"{API}?{urllib.parse.urlencode(q)}"
    last = None
    for n in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                body = json.loads(r.read().decode("utf-8"), strict=False)
            if body.get("code") != 0:
                raise RuntimeError(f"code={body.get('code')} msg={body.get('msg')}")
            return body["data"]
        except (OSError, RuntimeError, json.JSONDecodeError) as e:
            # OSError 覆盖 socket.timeout(py3.9)/TimeoutError/URLError/ConnectionError
            last = e; time.sleep(3 * (n + 1))   # 服务端会限流,退避久一点
    raise SystemExit(f"ERROR: 拉视频指标第 {page} 页失败(重试 {retries} 次): {last}")

def nint(x):
    try: return int(x)
    except (TypeError, ValueError): return 0
def nflt(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0

def new_acc():
    return dict(views=0, likes=0, comments=0, shares=0, subs=0, rev=0.0,
                apw=0.0, adw=0.0, aps=0.0, ads=0.0, n=0)

def add(acc, v, lk, cm, sh, sg, rev, avp, avd):
    acc["views"]+=v; acc["likes"]+=lk; acc["comments"]+=cm; acc["shares"]+=sh
    acc["subs"]+=sg; acc["rev"]+=rev
    acc["apw"]+=avp*v; acc["adw"]+=avd*v          # 按播放加权(numerator)
    acc["aps"]+=avp;  acc["ads"]+=avd;  acc["n"]+=1  # 简单平均(fallback)

def avg(acc, key):  # 稳健:有播放按加权,否则简单平均
    w = acc["apw"] if key=="ap" else acc["adw"]
    s = acc["aps"] if key=="ap" else acc["ads"]
    return round(w/acc["views"], 2) if acc["views"] else (round(s/acc["n"], 2) if acc["n"] else 0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default="")
    ap.add_argument("--channels-file", default="channel_ids.txt")
    ap.add_argument("--days", type=int, default=14, help="每次滚动窗口(天);频道指标增量累积,故取近两周即可")
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default=datetime.date.today().isoformat())
    ap.add_argument("--sleep", type=float, default=0.5, help="翻页间隔秒,节流避免打爆网关")
    ap.add_argument("--out-channel", default="channel_metrics_daily.csv")
    ap.add_argument("--out-video", default="video_summary.csv")
    args = ap.parse_args()

    token = get_token(args.token)
    end = args.end
    start = args.start or (datetime.date.fromisoformat(end) - datetime.timedelta(days=args.days)).isoformat()
    channel_ids = ""
    p = HERE / args.channels_file
    if p.exists():
        ids = [l.strip() for l in p.read_text().split() if l.strip()]
        channel_ids = ",".join(ids)
        print(f"[info] 限定 {len(ids)} 个频道, 窗口 {start}~{end}")

    ch, vid, vidmeta = {}, {}, {}
    page = 1
    while True:
        d = fetch_page(token, start, end, channel_ids, page)
        for c in d.get("collections", []):
            cid = c.get("channel_id"); vd = c.get("video_id"); dt = (c.get("date") or "")[:10]
            if not cid or not dt: continue
            row = (nint(c.get("views")), nint(c.get("likes")), nint(c.get("comments")),
                   nint(c.get("shares")), nint(c.get("subscribers_gained")),
                   nflt(c.get("estimated_revenue")), nflt(c.get("average_view_percentage")),
                   nflt(c.get("average_view_duration")))
            add(ch.setdefault((dt, cid), new_acc()), *row)
            if vd:
                add(vid.setdefault(vd, new_acc()), *row); vidmeta[vd] = cid
        last_page = d.get("last_page", page)
        if page == 1 or page % 10 == 0 or page >= last_page:
            print(f"[page {page}/{last_page}] 频道×天 {len(ch)} / 视频 {len(vid)}")
        if page >= last_page or not d.get("next_page_url"): break
        page += 1
        time.sleep(args.sleep)   # 节流:避免高频打运维网关被限流

    CHDR = ["date","channel_id","views","likes","comments","shares","subscribers_gained",
            "estimated_revenue","avg_view_pct","avg_view_duration"]
    # 频道×天:增量累积——读入已有,窗口内的行用新值覆盖,窗口外(更早)的历史保留
    merged = {}
    cpath = HERE / args.out_channel
    if cpath.exists():
        for r in csv.DictReader(open(cpath)):
            k = (r.get("date"), r.get("channel_id"))
            if k[0] and k[1]: merged[k] = [r.get(h,"") for h in CHDR]
    for (dt, cid) in ch:
        a = ch[(dt, cid)]
        merged[(dt, cid)] = [dt, cid, a["views"], a["likes"], a["comments"], a["shares"], a["subs"],
                             round(a["rev"],4), avg(a,"ap"), avg(a,"ad")]
    with open(cpath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(CHDR)
        for k in sorted(merged): w.writerow(merged[k])
    with open(HERE / args.out_video, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["video_id","channel_id","views","likes","comments","shares","subscribers_gained",
                    "estimated_revenue","avg_view_pct","avg_view_duration"])
        for vd in sorted(vid):
            a = vid[vd]
            w.writerow([vd, vidmeta.get(vd,""), a["views"], a["likes"], a["comments"], a["shares"],
                        a["subs"], round(a["rev"],4), avg(a,"ap"), avg(a,"ad")])
    tot = sum(a["rev"] for a in ch.values())
    print(f"[done] 频道×天 {len(ch)} 行 / 视频 {len(vid)} 行 / 窗口收益≈${tot:,.2f}")

if __name__ == "__main__":
    main()
