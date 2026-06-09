#!/usr/bin/env python3
"""
一站式: 批量频道 -> 拉公开数据(频道维度 + 视频维度) -> 生成可视化看板 HTML。

只拉公开数据 (API Key, 无 OAuth):
  频道维度: 订阅数 / 总播放 / 视频数
  视频维度: 发布 / 时长 / 播放 / 点赞 / 评论   (仅公开视频)

用法:
  python3 yt_report.py --file channel_ids.txt
  python3 yt_report.py UCxxxx UCyyyy --max 100 --out dashboard.html

产物:
  channels.csv  视频维度  videos.csv  看板  dashboard.html (用浏览器打开)

API Key 从 ~/.yt_key 读取 (或环境变量 YT_API_KEY)。
"""
import sys, os, json, csv, re, urllib.request, urllib.parse, argparse, pathlib, datetime

BASE = "https://www.googleapis.com/youtube/v3"

def load_key():
    k = os.environ.get("YT_API_KEY")
    if k: return k.strip()
    f = pathlib.Path.home() / ".yt_key"
    if f.exists(): return f.read_text().strip()
    sys.exit("ERROR: 没找到 API key (~/.yt_key 或 YT_API_KEY)。")

def api(endpoint, key, **params):
    params["key"] = key
    with urllib.request.urlopen(f"{BASE}/{endpoint}?{urllib.parse.urlencode(params)}") as r:
        return json.load(r)

def chunks(lst, n):
    for i in range(0, len(lst), n): yield lst[i:i+n]

def iso_dur_to_sec(s):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m: return 0
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h*3600 + mi*60 + se

def fmt_dur(sec):
    h, r = divmod(sec, 3600); m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def to_int(x):
    try: return int(x)
    except (TypeError, ValueError): return None

# ---------- 取数 ----------
def channel_dim(ids, key):
    out = {}
    for batch in chunks(ids, 50):
        d = api("channels", key, part="snippet,statistics,contentDetails",
                id=",".join(batch), maxResults=50)
        for it in d.get("items", []):
            sn, st = it.get("snippet", {}), it.get("statistics", {})
            out[it["id"]] = {
                "channel_id": it["id"],
                "title": sn.get("title", ""),
                "country": sn.get("country", ""),
                "published_at": sn.get("publishedAt", ""),
                "subscribers": to_int(st.get("subscriberCount")),
                "total_views": to_int(st.get("viewCount")),
                "videos_total": to_int(st.get("videoCount")),   # 含私有/unlisted
                "uploads": it.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", ""),
            }
    return out

def video_ids(uploads, key, cap=None):
    ids, token = [], None
    while uploads:
        try:
            d = api("playlistItems", key, part="contentDetails", playlistId=uploads,
                    maxResults=50, **({"pageToken": token} if token else {}))
        except urllib.error.HTTPError as e:
            if e.code == 404: return ids
            raise
        for it in d.get("items", []):
            ids.append(it["contentDetails"]["videoId"])
            if cap and len(ids) >= cap: return ids
        token = d.get("nextPageToken")
        if not token: return ids
    return ids

def video_dim(vids, key):
    rows = []
    for batch in chunks(vids, 50):
        d = api("videos", key, part="snippet,statistics,contentDetails", id=",".join(batch), maxResults=50)
        for it in d.get("items", []):
            sn, st, cd = it.get("snippet", {}), it.get("statistics", {}), it.get("contentDetails", {})
            sec = iso_dur_to_sec(cd.get("duration", ""))
            rows.append({
                "video_id": it["id"],
                "video_title": sn.get("title", ""),
                "published_at": sn.get("publishedAt", ""),
                "duration_sec": sec,
                "duration": fmt_dur(sec),
                "views": to_int(st.get("viewCount")),
                "likes": to_int(st.get("likeCount")),       # 隐藏 -> None
                "comments": to_int(st.get("commentCount")), # 关闭 -> None
                "url": f"https://youtu.be/{it['id']}",
            })
    return rows

# ---------- 看板 ----------
TEMPLATE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>YouTube 频道矩阵看板</title>
__CHARTJS__
<style>
 body{font-family:-apple-system,"PingFang SC",Segoe UI,sans-serif;margin:0;background:#0f1115;color:#e6e8eb}
 .wrap{max-width:1200px;margin:0 auto;padding:24px}
 h1{font-size:22px;margin:0 0 4px} .sub{color:#8b929c;font-size:13px;margin-bottom:20px}
 .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}
 .kpi{background:#1a1d24;border:1px solid #262a33;border-radius:10px;padding:16px}
 .kpi .v{font-size:26px;font-weight:700} .kpi .l{color:#8b929c;font-size:12px;margin-top:4px}
 .card{background:#1a1d24;border:1px solid #262a33;border-radius:10px;padding:16px;margin-bottom:20px}
 .card h2{font-size:15px;margin:0 0 12px}
 .grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #262a33;white-space:nowrap}
 th{color:#8b929c;font-weight:600;cursor:pointer;user-select:none}
 td.num,th.num{text-align:right} tr:hover td{background:#20242c}
 a{color:#5b9dff;text-decoration:none} .muted{color:#6b7280}
 canvas{max-height:280px}
 @media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<h1>YouTube 频道矩阵看板</h1>
<div class="sub">仅公开数据 · 生成于 __GEN__ · 数据来自 YouTube Data API v3</div>
<div class="kpis" id="kpis"></div>
<div class="card grid2">
 <div><h2>各频道订阅数</h2><canvas id="cSub"></canvas></div>
 <div><h2>各频道总播放</h2><canvas id="cViews"></canvas></div>
</div>
<div class="card grid2">
 <div><h2>月度发布量(按频道堆叠)</h2><canvas id="cCadence"></canvas></div>
 <div><h2>月度播放量(按发布月份汇总)</h2><canvas id="cTrend"></canvas></div>
</div>
<div class="card"><h2>频道维度</h2><div id="chTable"></div></div>
<div class="card"><h2>播放量 Top 视频(全矩阵)</h2><div id="vidTable"></div></div>
</div>
<script>
const CH = __CH__, VID = __VID__;
const fmt = n => n==null ? '<span class=muted>—</span>' : n.toLocaleString();
const pct = (a,b) => (a==null||!b) ? '<span class=muted>—</span>' : (a/b*100).toFixed(2)+'%';
const PALETTE = ['#5b9dff','#5bd1a0','#f7b955','#e06c75','#b18cff','#56c2d6','#d49bd4','#9aa7b5'];
// KPIs
const sum=(a,k)=>a.reduce((s,x)=>s+(x[k]||0),0);
document.getElementById('kpis').innerHTML = [
 ['频道数', CH.length],
 ['公开视频数', VID.length],
 ['总订阅', sum(CH,'subscribers')],
 ['总播放(频道口径)', sum(CH,'total_views')],
].map(([l,v])=>`<div class=kpi><div class=v>${v.toLocaleString()}</div><div class=l>${l}</div></div>`).join('');
// charts
const lbl = CH.map(c=>c.title);
const bar=(id,data,color)=>new Chart(document.getElementById(id),{type:'bar',
 data:{labels:lbl,datasets:[{data,backgroundColor:color}]},
 options:{plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#8b929c',maxRotation:60,minRotation:30}},y:{ticks:{color:'#8b929c'},grid:{color:'#262a33'}}}}});
bar('cSub',CH.map(c=>c.subscribers||0),'#5b9dff');
bar('cViews',CH.map(c=>c.total_views||0),'#5bd1a0');
// channel table (with derived public stats)
const byCh = {};
VID.forEach(v=>{(byCh[v.channel_id]=byCh[v.channel_id]||[]).push(v)});
CH.forEach(c=>{const vs=byCh[c.channel_id]||[]; c.pub_videos=vs.length;
 c.pub_views=vs.reduce((s,v)=>s+(v.views||0),0);
 c.avg_views=vs.length?Math.round(c.pub_views/vs.length):0;
 c.likes_sum=vs.reduce((s,v)=>s+(v.likes||0),0);
 c.comments_sum=vs.reduce((s,v)=>s+(v.comments||0),0);
 const top=vs.slice().sort((a,b)=>(b.views||0)-(a.views||0))[0]; c.top=top;});
function makeTable(el, cols, rows){
 const t=document.createElement('table');
 t.innerHTML='<thead><tr>'+cols.map((c,i)=>`<th class="${c.num?'num':''}" data-i=${i}>${c.h}</th>`).join('')+'</tr></thead><tbody></tbody>';
 const tb=t.querySelector('tbody');
 const render=data=>{tb.innerHTML=data.map(r=>'<tr>'+cols.map(c=>`<td class="${c.num?'num':''}">${c.f(r)}</td>`).join('')+'</tr>').join('')};
 render(rows);
 let asc={};
 t.querySelectorAll('th').forEach((th,i)=>th.onclick=()=>{asc[i]=!asc[i];
  rows.sort((a,b)=>{const va=cols[i].s(a),vb=cols[i].s(b);return (va>vb?1:va<vb?-1:0)*(asc[i]?1:-1)});render(rows)});
 el.innerHTML=''; el.appendChild(t);
}
makeTable(document.getElementById('chTable'),[
 {h:'频道',f:r=>`<a href=https://youtube.com/channel/${r.channel_id} target=_blank>${r.title}</a>`,s:r=>r.title},
 {h:'订阅',num:1,f:r=>fmt(r.subscribers),s:r=>r.subscribers||0},
 {h:'总播放',num:1,f:r=>fmt(r.total_views),s:r=>r.total_views||0},
 {h:'视频数(总)',num:1,f:r=>fmt(r.videos_total),s:r=>r.videos_total||0},
 {h:'公开视频',num:1,f:r=>fmt(r.pub_videos),s:r=>r.pub_videos},
 {h:'公开均播放',num:1,f:r=>fmt(r.avg_views),s:r=>r.avg_views},
 {h:'点赞率',num:1,f:r=>pct(r.likes_sum,r.pub_views),s:r=>r.pub_views?r.likes_sum/r.pub_views:0},
 {h:'评论率',num:1,f:r=>pct(r.comments_sum,r.pub_views),s:r=>r.pub_views?r.comments_sum/r.pub_views:0},
 {h:'最高播放视频',f:r=>r.top?`<a href=${r.top.url} target=_blank>${r.top.video_title}</a>`:'<span class=muted>—</span>',s:r=>r.top?r.top.views||0:0},
], CH);
const vidSorted = VID.slice().sort((a,b)=>(b.views||0)-(a.views||0));
makeTable(document.getElementById('vidTable'),[
 {h:'频道',f:r=>r.channel_title,s:r=>r.channel_title},
 {h:'视频',f:r=>`<a href=${r.url} target=_blank>${r.video_title}</a>`,s:r=>r.video_title},
 {h:'发布',f:r=>r.published_at.slice(0,10),s:r=>r.published_at},
 {h:'时长',num:1,f:r=>r.duration,s:r=>r.duration_sec},
 {h:'播放',num:1,f:r=>fmt(r.views),s:r=>r.views||0},
 {h:'点赞',num:1,f:r=>fmt(r.likes),s:r=>r.likes||0},
 {h:'评论',num:1,f:r=>fmt(r.comments),s:r=>r.comments||0},
 {h:'点赞率',num:1,f:r=>pct(r.likes,r.views),s:r=>r.views?(r.likes||0)/r.views:0},
 {h:'评论率',num:1,f:r=>pct(r.comments,r.views),s:r=>r.views?(r.comments||0)/r.views:0},
], vidSorted);

// ---- 发布节奏: 月度发布量(按频道堆叠) + 月度播放量(按发布月汇总) ----
const months = [...new Set(VID.map(v=>(v.published_at||'').slice(0,7)).filter(Boolean))].sort();
const cadenceSets = CH.map((c,i)=>({label:c.title,backgroundColor:PALETTE[i%PALETTE.length],
  data:months.map(m=>(byCh[c.channel_id]||[]).filter(v=>(v.published_at||'').slice(0,7)===m).length)}));
new Chart(document.getElementById('cCadence'),{type:'bar',data:{labels:months,datasets:cadenceSets},
 options:{plugins:{legend:{labels:{color:'#8b929c',boxWidth:12}}},
  scales:{x:{stacked:true,ticks:{color:'#8b929c'}},y:{stacked:true,ticks:{color:'#8b929c'},grid:{color:'#262a33'}}}}});
const trend = months.map(m=>VID.filter(v=>(v.published_at||'').slice(0,7)===m).reduce((s,v)=>s+(v.views||0),0));
new Chart(document.getElementById('cTrend'),{type:'line',
 data:{labels:months,datasets:[{data:trend,borderColor:'#5bd1a0',backgroundColor:'#5bd1a0',tension:.3,fill:false}]},
 options:{plugins:{legend:{display:false}},scales:{x:{ticks:{color:'#8b929c'}},y:{ticks:{color:'#8b929c'},grid:{color:'#262a33'}}}}});
</script></body></html>"""

def write_csv(path, rows, fields):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--max", type=int, default=None, help="每频道最多最近 N 条公开视频")
    ap.add_argument("--out", default="dashboard.html")
    a = ap.parse_args()
    ids = list(a.ids)
    if a.file:
        # 自动从文件里抓频道 ID (UC + 22 字符)，所以后台导出的 CSV 也能直接喂
        ids += re.findall(r"UC[0-9A-Za-z_-]{22}", open(a.file).read())
    seen, deduped = set(), []
    for x in ids:
        if x not in seen: seen.add(x); deduped.append(x)
    ids = deduped
    if not ids: sys.exit("ERROR: 没有频道 ID。")

    key = load_key()
    chd = channel_dim(ids, key)
    channels, videos = [], []
    units = (len(ids)+49)//50
    for cid in ids:
        c = chd.get(cid)
        if not c:
            sys.stderr.write(f"[warn] {cid} 无数据,跳过\n"); continue
        channels.append(c)
        vids = video_ids(c["uploads"], key, a.max)
        vrows = video_dim(vids, key)
        for r in vrows: r["channel_id"] = cid; r["channel_title"] = c["title"]
        videos += vrows
        units += (len(vids)+49)//50 * 2
        sys.stderr.write(f"[ok] {c['title']}: 订阅{c['subscribers']} 总播放{c['total_views']} 公开视频{len(vrows)}/{c['videos_total']}\n")

    write_csv("channels.csv", channels, ["channel_id","title","country","published_at","subscribers","total_views","videos_total"])
    write_csv("videos.csv", videos, ["channel_id","channel_title","video_id","video_title","published_at","duration","duration_sec","views","likes","comments","url"])
    # 若脚本同目录有 chart.umd.min.js 则内联(看板完全自包含,可离线/直接发给别人)
    libf = pathlib.Path(__file__).parent / "chart.umd.min.js"
    if libf.exists():
        chartjs = "<script>" + libf.read_text(encoding="utf-8") + "</script>"
    else:
        chartjs = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>'
    html = (TEMPLATE
            .replace("__CHARTJS__", chartjs)
            .replace("__GEN__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__CH__", json.dumps(channels, ensure_ascii=False))
            .replace("__VID__", json.dumps(videos, ensure_ascii=False)))
    pathlib.Path(a.out).write_text(html, encoding="utf-8")
    sys.stderr.write(f"\n[done] {len(channels)} 频道 / {len(videos)} 公开视频，约耗 {units} quota units\n")
    sys.stderr.write(f"       channels.csv  videos.csv  {a.out}\n")

if __name__ == "__main__":
    main()
