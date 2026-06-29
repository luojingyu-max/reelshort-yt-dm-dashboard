#!/usr/bin/env python3
"""
拉取 YouTube 已授权频道的「预估收益」数据 -> revenue_daily.csv

数据源(服务端导出接口, 非公开 API):
  GET http://v-adm-api.stardustgod.com/api/youtube/revenue
  参数: token(必填) start_date end_date channel_ids(逗号分隔,默认全部) page page_size(<=100)
  返回: Laravel 分页, data.collections[] = {date, channel_id, estimated_revenue(float), currency}

与播放量不同, 收益历史是接口可查的(按日期区间), 所以每次跑直接拉一个宽区间覆盖,
无需逐日快照累积。输出按 (date, channel_id) 去重(后到覆盖先到)。

token 从环境变量 REVENUE_API_TOKEN 读取(本地可 --token 传)。

用法:
  REVENUE_API_TOKEN=xxx python3 revenue_report.py
  python3 revenue_report.py --token xxx --start 2026-01-01 --end 2026-06-29
"""
import sys, os, csv, json, time, argparse, pathlib, datetime
import urllib.request, urllib.parse, urllib.error

API = "http://v-adm-api.stardustgod.com/api/youtube/revenue"
HERE = pathlib.Path(__file__).parent

def get_token(cli):
    t = cli or os.environ.get("REVENUE_API_TOKEN")
    if not t:
        sys.exit("ERROR: 没有 token (设 REVENUE_API_TOKEN 环境变量, 或 --token 传入)。")
    return t.strip()

def fetch_page(token, start, end, channel_ids, page, page_size=100, retries=4):
    q = {"token": token, "start_date": start, "end_date": end,
         "page": page, "page_size": page_size}
    if channel_ids:
        q["channel_ids"] = channel_ids
    url = f"{API}?{urllib.parse.urlencode(q)}"
    last = None
    for n in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                body = json.load(r)
            if body.get("code") != 0:
                raise RuntimeError(f"接口返回 code={body.get('code')} msg={body.get('msg')}")
            return body["data"]
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
            last = e
            time.sleep(2 * (n + 1))
    raise SystemExit(f"ERROR: 拉收益第 {page} 页失败(重试 {retries} 次): {last}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default="")
    ap.add_argument("--channels-file", default="channel_ids.txt",
                    help="只拉这些频道(每行一个 UC ID); 传 'all' 则拉全部授权频道")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default=datetime.date.today().isoformat())
    ap.add_argument("--out", default="revenue_daily.csv")
    args = ap.parse_args()

    token = get_token(args.token)

    channel_ids = ""
    if args.channels_file.lower() != "all":
        p = HERE / args.channels_file
        if p.exists():
            ids = [l.strip() for l in p.read_text().split() if l.strip()]
            channel_ids = ",".join(ids)
            print(f"[info] 限定 {len(ids)} 个看板频道")
        else:
            print(f"[warn] 找不到 {args.channels_file}, 改拉全部授权频道")

    # (date, channel_id) -> row, 后到覆盖先到(同键去重)
    rows = {}
    page = 1
    while True:
        d = fetch_page(token, args.start, args.end, channel_ids, page)
        for c in d.get("collections", []):
            cid = c.get("channel_id"); dt = c.get("date")
            if not cid or not dt:
                continue
            rows[(dt, cid)] = {
                "date": dt[:10],
                "channel_id": cid,
                "estimated_revenue": c.get("estimated_revenue", 0) or 0,
                "currency": c.get("currency", "USD") or "USD",
            }
        last_page = d.get("last_page", page)
        print(f"[page {page}/{last_page}] 累计 {len(rows)} 条")
        if page >= last_page or not d.get("next_page_url"):
            break
        page += 1

    out = HERE / args.out
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "channel_id", "estimated_revenue", "currency"])
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])
    total = sum(float(r["estimated_revenue"]) for r in rows.values())
    print(f"[done] {len(rows)} 条 / {args.start}~{args.end}  总预估收益≈${total:,.2f}  ->  {out}")

if __name__ == "__main__":
    main()
