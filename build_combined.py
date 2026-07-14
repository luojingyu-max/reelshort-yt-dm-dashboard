#!/usr/bin/env python3
"""
合并 YouTube + Dailymotion 的已生成 CSV -> 一个跨平台看板(支持平台/频道/日期筛选)。

读入(需先跑过 yt_report.py 和 dm_report.py):
  YouTube : channels.csv     videos.csv
  Dailymotion: dm_channels.csv  dm_videos.csv
输出:
  combined_site/index.html

用法: python3 build_combined.py
"""
import csv, json, pathlib, datetime, sys

HERE = pathlib.Path(__file__).parent

def load(path, platform):
    p = HERE / path
    if not p.exists():
        sys.stderr.write(f"[warn] 缺少 {path},跳过 {platform}\n"); return []
    rows = list(csv.DictReader(open(p)))
    for r in rows: r["platform"] = platform
    return rows

def to_int(x):
    try: return int(x)
    except (TypeError, ValueError): return None

def main():
    ch = load("channels.csv", "YouTube") + load("dm_channels.csv", "Dailymotion")
    vd = load("videos.csv", "YouTube") + load("dm_videos.csv", "Dailymotion")

    channels = [{
        "platform": r["platform"], "channel_id": r["channel_id"], "title": r["title"],
        "country": r.get("country", ""),
        "subscribers": to_int(r.get("subscribers")), "total_views": to_int(r.get("total_views")),
        "videos_total": to_int(r.get("videos_total")),
    } for r in ch]
    videos = [{
        "platform": r["platform"], "channel_id": r["channel_id"], "channel_title": r["channel_title"],
        "video_id": r["video_id"], "video_title": r["video_title"], "published_at": r.get("published_at", ""),
        "duration": r.get("duration", ""), "duration_sec": to_int(r.get("duration_sec")) or 0,
        "views": to_int(r.get("views")), "likes": to_int(r.get("likes")), "comments": to_int(r.get("comments")),
        "url": r.get("url", ""),
    } for r in vd]

    # 频道 -> 负责人:DM 按频道名(dm_owners.csv),YouTube 按频道ID(yt_owners.csv)
    dm_owners, yt_owners = {}, {}
    p1 = HERE / "dm_owners.csv"
    if p1.exists():
        for r in csv.DictReader(open(p1)): dm_owners[r["title"].strip()] = r["operator"].strip()
    p2 = HERE / "yt_owners.csv"
    if p2.exists():
        for r in csv.DictReader(open(p2)): yt_owners[r["channel_id"].strip()] = r["operator"].strip()
    for c in channels:
        if c["platform"] == "Dailymotion":
            c["operator"] = dm_owners.get(c["title"].strip(), "未分配")
        else:
            c["operator"] = yt_owners.get(c["channel_id"].strip(), "未分配")
    opmap = {(c["platform"], c["channel_id"]): c["operator"] for c in channels}
    for v in videos:
        v["operator"] = opmap.get((v["platform"], v["channel_id"]), "")

    # YouTube 预估收益(按天×频道) revenue_daily.csv -> {channel_id: [[date, rev], ...]}
    rev = {}
    rev_dates = []
    rvp = HERE / "revenue_daily.csv"
    if rvp.exists():
        for r in csv.DictReader(open(rvp)):
            cid = r.get("channel_id"); dt = (r.get("date") or "")[:10]
            if not cid or not dt: continue
            try: amt = float(r.get("estimated_revenue") or 0)
            except (TypeError, ValueError): amt = 0.0
            rev.setdefault(cid, []).append([dt, amt]); rev_dates.append(dt)
    for k in rev: rev[k].sort(key=lambda x: x[0])

    # 默认日期范围要同时覆盖「视频发布日」与「收益日」,否则最新收益会被默认筛选挡掉
    dates = sorted([v["published_at"][:10] for v in videos if v.get("published_at")] + rev_dates)
    dmin = dates[0] if dates else "2020-01-01"
    dmax = dates[-1] if dates else datetime.date.today().isoformat()

    # 每日快照历史(逐日累积,API 无法回填)
    hist = []
    hp = HERE / "history" / "daily.csv"
    if hp.exists():
        for r in csv.DictReader(open(hp)):
            hist.append({"date": r["date"], "platform": r["platform"], "channel_id": r["channel_id"],
                         "total_views": to_int(r.get("total_views"))})
    # 视频级每日历史 -> {video_id: [[date, views], ...]}
    vhist = {}
    vp = HERE / "history" / "videos_daily.csv"
    if vp.exists():
        for r in csv.DictReader(open(vp)):
            vhist.setdefault(r["video_id"], []).append([r["date"], to_int(r.get("views")) or 0])
    # DM 爬虫口径(Studio 准数 + 真实日增,按 video_id 串联)dm_crawler_daily.csv
    crawl = {}
    cp = HERE / "dm_crawler_daily.csv"
    if cp.exists():
        for r in csv.DictReader(open(cp)):
            vid = r.get("video_id")
            if not vid: continue
            crawl.setdefault(vid, []).append([r["date"], to_int(r.get("total_views")), to_int(r.get("day_views"))])
    for k in crawl: crawl[k].sort(key=lambda x: x[0])

    # 视频维度聚合(来自 videoRevenue 接口)
    # 频道×天 -> {channel_id: [[date, views, subs, rev, avp, avd, likes, comments, shares], ...]}
    cm = {}
    cmp_ = HERE / "channel_metrics_daily.csv"
    if cmp_.exists():
        for r in csv.DictReader(open(cmp_)):
            cid = r.get("channel_id"); dt = (r.get("date") or "")[:10]
            if not cid or not dt: continue
            cm.setdefault(cid, []).append([dt, to_int(r.get("views")) or 0,
                to_int(r.get("subscribers_gained")) or 0, round(float(r.get("estimated_revenue") or 0), 4),
                float(r.get("avg_view_pct") or 0), float(r.get("avg_view_duration") or 0),
                to_int(r.get("likes")) or 0, to_int(r.get("comments")) or 0, to_int(r.get("shares")) or 0])
    for k in cm: cm[k].sort(key=lambda x: x[0])
    # 频道指标日期也纳入默认范围,否则最近的指标会被默认筛选挡掉
    _cmd = [row[0] for rows in cm.values() for row in rows]
    if _cmd:
        dmin = min(dmin, min(_cmd)); dmax = max(dmax, max(_cmd))
    # 每视频窗口汇总 -> {video_id: [rev, avp, avd, views, likes, comments, shares]}
    vs = {}
    vsp = HERE / "video_summary.csv"
    if vsp.exists():
        for r in csv.DictReader(open(vsp)):
            vid = r.get("video_id")
            if not vid: continue
            vs[vid] = [round(float(r.get("estimated_revenue") or 0), 4),
                       float(r.get("avg_view_pct") or 0), float(r.get("avg_view_duration") or 0),
                       to_int(r.get("views")) or 0, to_int(r.get("likes")) or 0,
                       to_int(r.get("comments")) or 0, to_int(r.get("shares")) or 0]

    # chart.js 始终走 CDN 外链(不再内联 205KB),减小单文件体积、降低 surge 传输被掐断的概率;
    # 浏览器还能跨站缓存 jsdelivr。pinned 到 4.4.1 与本地 chart.umd.min.js 版本一致,避免大版本漂移。
    chartjs = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>'

    html = (TEMPLATE
            .replace("__CHARTJS__", chartjs)
            .replace("__GEN__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__DMIN__", dmin).replace("__DMAX__", dmax)
            .replace("__CH__", json.dumps(channels, ensure_ascii=False))
            .replace("__VID__", json.dumps(videos, ensure_ascii=False))
            .replace("__HIST__", json.dumps(hist, ensure_ascii=False))
            .replace("__VHIST__", json.dumps(vhist, ensure_ascii=False))
            .replace("__CRAWL__", json.dumps(crawl, ensure_ascii=False))
            .replace("__REV__", json.dumps(rev, ensure_ascii=False))
            .replace("__CM__", json.dumps(cm, ensure_ascii=False))
            .replace("__VS__", json.dumps(vs, ensure_ascii=False)))
    out = HERE / "combined_site" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"[done] {len(channels)} 频道 / {len(videos)} 视频  ->  {out}")
    print(f"       日期范围 {dmin} ~ {dmax}")

TEMPLATE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>YouTube × Dailymotion 跨平台矩阵看板</title>
__CHARTJS__
<style>
 body{font-family:-apple-system,"PingFang SC",Segoe UI,sans-serif;margin:0;background:#0f1115;color:#e6e8eb}
 .wrap{max-width:1240px;margin:0 auto;padding:24px}
 h1{font-size:22px;margin:0 0 4px} .sub{color:#8b929c;font-size:13px;margin-bottom:18px}
 .controls{display:flex;flex-wrap:wrap;gap:14px;align-items:center;background:#1a1d24;border:1px solid #262a33;border-radius:10px;padding:14px;margin-bottom:20px;position:relative}
 .controls label{font-size:12px;color:#8b929c;margin-right:6px}
 .seg button{background:#262a33;color:#cfd3da;border:0;padding:7px 12px;cursor:pointer;font-size:13px}
 .seg button:first-child{border-radius:7px 0 0 7px} .seg button:last-child{border-radius:0 7px 7px 0}
 .seg button.on{background:#5b9dff;color:#fff}
 input[type=date]{background:#0f1115;color:#e6e8eb;border:1px solid #313742;border-radius:6px;padding:6px 8px;font-size:13px}
 .lfilt{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;margin:0 0 12px}
 .lfilt label{font-size:12px;color:#8b929c}
 .lfilt select{background:#0f1115;color:#e6e8eb;border:1px solid #313742;border-radius:6px;padding:6px 8px;font-size:13px;max-width:260px}
 .ms{position:relative;display:inline-block}
 .ms-panel{position:absolute;top:38px;left:0;z-index:30;background:#1a1d24;border:1px solid #313742;border-radius:8px;padding:8px;min-width:170px;max-height:300px;overflow:auto;box-shadow:0 8px 24px rgba(0,0,0,.5);display:none}
 .ms-panel.open{display:block}
 .ms-panel .row{display:flex;align-items:center;gap:6px;padding:3px 4px;font-size:13px;white-space:nowrap;color:#e6e8eb;cursor:pointer;margin:0}
 .ms-panel hr{border:0;border-top:1px solid #262a33;margin:6px 0}
 .btn{background:#262a33;color:#cfd3da;border:1px solid #313742;border-radius:6px;padding:7px 12px;cursor:pointer;font-size:13px}
 .panel{position:absolute;top:64px;left:14px;z-index:20;background:#1a1d24;border:1px solid #313742;border-radius:10px;padding:12px;width:340px;max-height:360px;overflow:auto;box-shadow:0 8px 24px rgba(0,0,0,.5);display:none}
 .panel.open{display:block}
 .panel input[type=search]{width:100%;box-sizing:border-box;background:#0f1115;color:#e6e8eb;border:1px solid #313742;border-radius:6px;padding:6px 8px;margin-bottom:8px}
 .panel .grp{color:#8b929c;font-size:11px;margin:8px 0 4px;text-transform:uppercase}
 .panel .row{display:flex;align-items:center;gap:6px;padding:3px 2px;font-size:13px}
 .panel .row label{color:#e6e8eb;margin:0;cursor:pointer;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:22px}
 .kpi{background:#1a1d24;border:1px solid #262a33;border-radius:10px;padding:16px}
 .kpi .v{font-size:24px;font-weight:700} .kpi .l{color:#8b929c;font-size:12px;margin-top:4px}
 .card{background:#1a1d24;border:1px solid #262a33;border-radius:10px;padding:16px;margin-bottom:20px}
 .card h2{font-size:15px;margin:0 0 12px}
 .ins{margin:0;padding-left:20px} .ins li{margin:7px 0;line-height:1.65;color:#cdd2d9;font-size:13.5px}
 .ins b{color:#fff}
 .grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #262a33;white-space:nowrap}
 th{color:#8b929c;font-weight:600;cursor:pointer;user-select:none} td.num,th.num{text-align:right}
 tr:hover td{background:#20242c} a{color:#5b9dff;text-decoration:none} .muted{color:#6b7280}
 .tag{font-size:11px;padding:1px 6px;border-radius:4px} .yt{background:#3a1d1d;color:#ff7b7b} .dm{background:#1d2a3a;color:#6db3ff}
 .tbar{display:flex;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap}
 .tbar .btn{padding:5px 10px} .tinfo{color:#8b929c;font-size:12px}
 .pager{margin-left:auto;display:flex;align-items:center;gap:6px;color:#8b929c;font-size:12px}
 .pager select{background:#0f1115;color:#e6e8eb;border:1px solid #313742;border-radius:6px;padding:3px 6px}
 canvas{max-height:280px}
 @media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<h1>YouTube × Dailymotion 跨平台矩阵看板</h1>
<div class="sub">仅公开数据 · 生成于 __GEN__ · 频道级(订阅/总播放)为账号累计值,不随日期变;视频级指标随日期筛选</div>

<div class="controls">
 <div><label>平台</label><span class="seg" id="segPlat">
   <button data-p="all" class="on">全部</button><button data-p="YouTube">YouTube</button><button data-p="Dailymotion">Dailymotion</button>
 </span></div>
 <div><label>发布日期</label>
   <input type="date" id="dFrom"> ~ <input type="date" id="dTo">
 </div>
 <button class="btn" id="resetBtn">重置</button>
</div>

<div class="kpis" id="kpis"></div>
<div class="card"><h2>数据总结(随筛选自动更新)</h2><ul class="ins" id="insights"></ul></div>
<div class="card grid2">
 <div><h2>各频道订阅/粉丝(累计 · Top20)</h2><canvas id="cSub"></canvas></div>
 <div><h2>各频道区间播放(Top20)</h2><canvas id="cViews"></canvas></div>
</div>
<div class="card">
 <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;flex-wrap:wrap">
   <h2 style="margin:0">分日播放(按发布日期)</h2>
   <span class="seg" id="segMode"><button data-m="channel" class="on">Top10 频道</button><button data-m="video">Top10 视频</button></span>
 </div>
 <div class="sub" style="margin-bottom:10px">按视频发布日期聚合的播放量。<b>频道模式</b>:播放最高的 Top10 频道各一条日线;<b>视频模式</b>:Top10 单视频的播放量。用上方"平台/发布日期"筛选可换一批。</div>
 <canvas id="cDaily" style="max-height:360px"></canvas>
</div>
<div class="card" id="revCard">
 <h2>YouTube 预估收益(已授权频道)</h2>
 <div class="sub" style="margin-bottom:10px">来自服务端授权接口的 estimated_revenue(USD),按天×频道。受上方"发布日期"区间联动(此处按<b>收益日期</b>累计)。收益数据一般 T+2~3 到账,故最新一两天可能偏低。仅 YouTube 有此数据。</div>
 <div class="grid2">
  <div><canvas id="cRev"></canvas></div>
  <div><canvas id="cRevOp"></canvas></div>
 </div>
</div>
<div class="card">
 <h2>单视频每日趋势(搜索选择)</h2>
 <div class="sub" style="margin-bottom:10px">标 <b>★准</b> 的视频用爬虫口径(Studio 准数 + 真实当日新增 + 历史);其余为公开 API 快照(从今日起逐日累积)。搜索标题选一条。</div>
 <div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap">
  <input type="search" id="vSearch" placeholder="搜索视频标题…" style="flex:1;min-width:220px;background:#0f1115;color:#e6e8eb;border:1px solid #313742;border-radius:6px;padding:7px 10px">
  <select id="vSelect" style="flex:2;min-width:280px;background:#0f1115;color:#e6e8eb;border:1px solid #313742;border-radius:6px;padding:7px 10px"></select>
 </div>
 <canvas id="cVid" style="max-height:320px"></canvas>
</div>
<div class="card" id="revChCard">
 <h2>单频道每日收益趋势</h2>
 <div class="sub" style="margin-bottom:10px">选一个 YouTube 频道,看它在所选区间内的每日预估收益($)。下拉默认按区间收益从高到低排序。受上方"发布日期"区间联动。仅 YouTube 有此数据。</div>
 <div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap">
  <input type="search" id="rvSearch" placeholder="搜索频道名…" style="flex:1;min-width:220px;background:#0f1115;color:#e6e8eb;border:1px solid #313742;border-radius:6px;padding:7px 10px">
  <select id="rvSelect" style="flex:2;min-width:280px;background:#0f1115;color:#e6e8eb;border:1px solid #313742;border-radius:6px;padding:7px 10px"></select>
 </div>
 <canvas id="cRevCh" style="max-height:320px"></canvas>
</div>
<div class="card">
 <h2 id="opTitle">人效比</h2>
 <div class="sub" style="margin-bottom:10px">按负责人聚合(DM 来自 owner.xlsx、YouTube 来自 YouTube账号.xlsx)。<b>单视频均播放</b>是人效核心(产出质量),<b>区间视频数</b>是产出量。「全部」时为双平台汇总对比。受平台/日期筛选联动。</div>
 <div class="grid2">
  <div><canvas id="cOpViews"></canvas></div>
  <div><canvas id="cOpAvg"></canvas></div>
 </div>
 <div id="opTable" style="margin-top:14px"></div>
</div>
<div class="card"><h2>频道维度</h2>
 <div class="sub" style="margin-bottom:8px">注:<b>区间新增订阅</b>=所选日期区间内<b>累计新涨的订阅数</b>(YouTube subscribersGained 毛增,不扣退订),<b>不是账号当前总粉丝数</b>;缩短日期区间该值会变小。总粉丝看「订阅/粉丝」列。</div>
 <div class="lfilt"><label>负责人</label>
   <div class="ms" id="chOpMs"><button class="btn ms-btn" type="button" data-label="负责人">负责人 ▾</button><div class="ms-panel"></div></div>
   <span class="muted" style="font-size:12px">(可多选 · 发布日期用顶部筛选)</span></div>
 <div id="chTable"></div></div>
<div class="card"><h2>Top 视频(区间内)</h2>
 <div class="lfilt"><label>负责人</label>
   <div class="ms" id="vidOpMs"><button class="btn ms-btn" type="button" data-label="负责人">负责人 ▾</button><div class="ms-panel"></div></div>
   <label>频道</label><select id="vidTblCh"></select>
   <span class="muted" style="font-size:12px">(可多选 · 发布日期用顶部筛选)</span></div>
 <div id="vidTable"></div></div>
</div>
<script>
const CH=__CH__, VID=__VID__, HIST=__HIST__, VHIST=__VHIST__, CRAWL=__CRAWL__, REV=__REV__, CM=__CM__, VS=__VS__, DMIN="__DMIN__", DMAX="__DMAX__";
const usd=n=>n==null?'<span class=muted>—</span>':'$'+Number(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const dur=s=>{s=Math.round(s||0);return Math.floor(s/60)+':'+String(s%60).padStart(2,'0');};
const PALETTE=['#5b9dff','#5bd1a0','#f7b955','#e06c75','#b18cff','#56c2d6','#d49bd4','#9aa7b5'];
const fmt=n=>n==null?'<span class=muted>—</span>':Number(n).toLocaleString();
const wan=n=>n==null?'—':(n>=10000?(n/10000).toFixed(1)+'万':Math.round(n).toLocaleString());
const pct=(a,b)=>(a==null||!b)?'<span class=muted>—</span>':(a/b*100).toFixed(2)+'%';
const key=x=>x.platform+'|'+x.channel_id;
const tag=p=>`<span class="tag ${p==='YouTube'?'yt':'dm'}">${p==='YouTube'?'YT':'DM'}</span>`;
let platform='all', dFrom=DMIN, dTo=DMAX, charts={}, chartMode='channel';
// 局部筛选(仅作用于对应的表)
let baseFch=[], baseFvid=[], chTblOps=new Set(), vidTblOps=new Set(), vidTblCh='all';

const chPass=c=>(platform==='all'||c.platform===platform);
const vidPass=v=>{const d=(v.published_at||'').slice(0,10);
  return (platform==='all'||v.platform===platform)&&d>=dFrom&&d<=dTo;};

function setChart(id,cfg){ if(charts[id])charts[id].destroy(); charts[id]=new Chart(document.getElementById(id),cfg); }
const axc={color:'#8b929c'}, grd={color:'#262a33'};

function render(){
 const fch=CH.filter(chPass), fvid=VID.filter(vidPass);
 const byCh={}; fvid.forEach(v=>{(byCh[key(v)]=byCh[key(v)]||[]).push(v)});
 fch.forEach(c=>{const vs=byCh[key(c)]||[]; c._n=vs.length;
   c._views=vs.reduce((s,v)=>s+(v.views||0),0);
   c._likes=vs.reduce((s,v)=>s+(v.likes||0),0);
   c._comments=vs.reduce((s,v)=>s+(v.comments||0),0);
   c._avg=vs.length?Math.round(c._views/vs.length):0;
   c._top=vs.slice().sort((a,b)=>(b.views||0)-(a.views||0))[0];});
 // 各频道区间预估收益(按收益日期落在 [dFrom,dTo] 累计;仅 YouTube)
 fch.forEach(c=>{ c._rev = c.platform==='YouTube'
   ? (REV[c.channel_id]||[]).reduce((s,a)=>s+(a[0]>=dFrom&&a[0]<=dTo?a[1]:0),0) : 0; });
 // 各频道视频维度指标(CM=[date,views,subs,rev,avp,avd,likes,comments,shares];完播率/时长按播放加权)
 fch.forEach(c=>{
   let vw=0,sg=0,rv=0,apw=0,adw=0,aps=0,ads=0,lk=0,cm=0,sh=0,n=0;
   (CM[c.channel_id]||[]).forEach(a=>{ if(a[0]>=dFrom&&a[0]<=dTo){
     vw+=a[1]; sg+=a[2]; rv+=a[3]; apw+=a[4]*a[1]; adw+=a[5]*a[1]; aps+=a[4]; ads+=a[5]; lk+=a[6]; cm+=a[7]; sh+=a[8]; n++; }});
   c._subs=sg;
   c._compl = vw? apw/vw : (n? aps/n : null);   // 完播率(按播放加权;无播放退化简单平均)
   c._avd   = vw? adw/vw : (n? ads/n : null);   // 平均观看时长(秒)
   c._eng   = vw? (lk+cm+sh)/vw*100 : null;     // 互动率 %
   c._rpm   = vw? rv/vw*1000 : null;            // RPM = 收益/播放×1000
 });
 // DM 无收益:隐藏收益相关卡片/KPI/图表
 const showRev = platform!=='Dailymotion';
 document.getElementById('revCard').style.display = showRev?'':'none';
 document.getElementById('revChCard').style.display = showRev?'':'none';

 // KPI
 const sum=(a,k)=>a.reduce((s,x)=>s+(x[k]||0),0);
 const kpiItems=[
  ['频道数',fch.length],['区间视频数',fvid.length],
  ['总订阅/粉丝(累计)',sum(fch,'subscribers')],['区间播放合计',sum(fvid,'views')],
 ];
 if(showRev) kpiItems.push(['区间预估收益',sum(fch,'_rev'),usd]);
 document.getElementById('kpis').innerHTML=kpiItems.map(([l,v,f])=>`<div class=kpi><div class=v>${f?f(v):v.toLocaleString()}</div><div class=l>${l}</div></div>`).join('');
 document.getElementById('insights').innerHTML=buildInsights(fch,fvid).map(b=>`<li>${b}</li>`).join('');

 // bar: subscribers (lifetime) top20
 const bySub=fch.slice().sort((a,b)=>(b.subscribers||0)-(a.subscribers||0)).slice(0,20);
 setChart('cSub',{type:'bar',data:{labels:bySub.map(c=>c.title),
   datasets:[{data:bySub.map(c=>c.subscribers||0),backgroundColor:bySub.map(c=>c.platform==='YouTube'?'#e06c75':'#5b9dff')}]},
   options:{plugins:{legend:{display:false}},scales:{x:{ticks:{...axc,maxRotation:60,minRotation:40}},y:{ticks:axc,grid:grd}}}});
 // bar: in-range views top20
 const byV=fch.slice().sort((a,b)=>b._views-a._views).slice(0,20);
 setChart('cViews',{type:'bar',data:{labels:byV.map(c=>c.title),
   datasets:[{data:byV.map(c=>c._views),backgroundColor:byV.map(c=>c.platform==='YouTube'?'#e06c75':'#5b9dff')}]},
   options:{plugins:{legend:{display:false}},scales:{x:{ticks:{...axc,maxRotation:60,minRotation:40}},y:{ticks:axc,grid:grd}}}});
 // 分日播放(按发布日期)
 const allDates=[...new Set(fvid.map(v=>(v.published_at||'').slice(0,10)).filter(Boolean))].sort();
 if(chartMode==='channel'){
   const top=fch.slice().sort((a,b)=>b._views-a._views).slice(0,10);
   const ds=top.map((c,i)=>{const byd={};
     (byCh[key(c)]||[]).forEach(v=>{const d=(v.published_at||'').slice(0,10); byd[d]=(byd[d]||0)+(v.views||0);});
     return {label:c.title,data:allDates.map(d=>byd[d]||0),borderColor:PALETTE[i%PALETTE.length],
       backgroundColor:PALETTE[i%PALETTE.length],tension:.3,pointRadius:2,fill:false};});
   setChart('cDaily',{type:'line',data:{labels:allDates,datasets:ds},
     options:{interaction:{mode:'nearest'},plugins:{legend:{labels:{color:'#8b929c',boxWidth:12}}},
       scales:{x:{ticks:axc},y:{ticks:axc,grid:grd,title:{display:true,text:'当日播放(按发布日)',color:'#8b929c'}}}}});
 } else {
   const topv=fvid.slice().sort((a,b)=>(b.views||0)-(a.views||0)).slice(0,10);
   setChart('cDaily',{type:'bar',data:{labels:topv.map(v=>v.video_title.length>24?v.video_title.slice(0,24)+'…':v.video_title),
     datasets:[{label:'播放',data:topv.map(v=>v.views||0),backgroundColor:topv.map(v=>v.platform==='YouTube'?'#e06c75':'#5b9dff')}]},
     options:{indexAxis:'y',plugins:{legend:{display:false},
       tooltip:{callbacks:{afterLabel:ctx=>`频道:${topv[ctx.dataIndex].channel_title}　发布:${(topv[ctx.dataIndex].published_at||'').slice(0,10)}`}}},
       scales:{x:{ticks:axc,grid:grd},y:{ticks:{...axc,autoSkip:false}}}}});
 }

 // 日预估收益趋势(选中 YouTube 频道按收益日汇总;DM tab 跳过)
 if(showRev){
   const revDays={};
   fch.forEach(c=>{ if(c.platform!=='YouTube') return;
     (REV[c.channel_id]||[]).forEach(a=>{ if(a[0]>=dFrom&&a[0]<=dTo) revDays[a[0]]=(revDays[a[0]]||0)+a[1]; }); });
   const rDates=Object.keys(revDays).sort();
   setChart('cRev',{type:'line',data:{labels:rDates,datasets:[{label:'日预估收益($)',
     data:rDates.map(d=>+revDays[d].toFixed(2)),borderColor:'#5bd1a0',backgroundColor:'#5bd1a0',tension:.3,pointRadius:1,fill:false}]},
     options:{plugins:{legend:{display:false},title:{display:true,text:'日预估收益趋势($)',color:'#cdd2d9'}},
       scales:{x:{ticks:axc},y:{ticks:axc,grid:grd}}}});
 }

 // tables
 // 人效比(按负责人聚合;全部=双平台汇总对比)
 const ops={}, ens=o=>ops[o]=ops[o]||{op:o,plat:'',nc:0,nv:0,views:0,likes:0,rev:0};
 const setp=(o,p)=>o.plat=(o.plat===''?p:(o.plat===p?o.plat:'混合'));
 fch.forEach(c=>{if(c.operator){const o=ens(c.operator); o.nc++; o.rev+=c._rev||0; setp(o,c.platform);}});
 fvid.forEach(v=>{if(v.operator){const o=ens(v.operator); o.nv++; o.views+=v.views||0; o.likes+=v.likes||0; setp(o,v.platform);}});
 const opArr=Object.values(ops).sort((a,b)=>b.views-a.views);
 opArr.forEach(o=>o.avg=o.nv?Math.round(o.views/o.nv):0);
 document.getElementById('opTitle').textContent = platform==='all'?'人效比(双平台汇总对比)':(platform==='YouTube'?'人效比(按 YouTube 负责人)':'人效比(按 DM 负责人)');
 const opL=opArr.map(o=>o.op), opColor=opArr.map(o=>o.plat==='YouTube'?'#e06c75':'#5b9dff');
 setChart('cOpViews',{type:'bar',data:{labels:opL,datasets:[{data:opArr.map(o=>o.views),backgroundColor:opColor}]},
   options:{plugins:{legend:{display:false},title:{display:true,text:'各负责人 · 区间播放合计',color:'#cdd2d9'}},scales:{x:{ticks:axc},y:{ticks:axc,grid:grd}}}});
 setChart('cOpAvg',{type:'bar',data:{labels:opL,datasets:[{data:opArr.map(o=>o.avg),backgroundColor:opColor}]},
   options:{plugins:{legend:{display:false},title:{display:true,text:'各负责人 · 单视频均播放(人效)',color:'#cdd2d9'}},scales:{x:{ticks:axc},y:{ticks:axc,grid:grd}}}});
 // 各负责人 · 区间预估收益(画在收益卡片的 cRevOp;DM tab 跳过)
 if(showRev){
   const opR=opArr.slice().sort((a,b)=>(b.rev||0)-(a.rev||0));
   setChart('cRevOp',{type:'bar',data:{labels:opR.map(o=>o.op),datasets:[{data:opR.map(o=>+(o.rev||0).toFixed(2)),
     backgroundColor:opR.map(o=>o.plat==='YouTube'?'#5bd1a0':'#56c2d6')}]},
     options:{plugins:{legend:{display:false},title:{display:true,text:'各负责人 · 区间预估收益($)',color:'#cdd2d9'}},scales:{x:{ticks:axc},y:{ticks:axc,grid:grd}}}});
 }
 makeTable(document.getElementById('opTable'),[
   {h:'平台',f:r=>r.plat==='YouTube'?tag('YouTube'):r.plat==='Dailymotion'?tag('Dailymotion'):'混合',s:r=>r.plat},
   {h:'负责人',f:r=>r.op,s:r=>r.op},
   {h:'频道数',num:1,f:r=>fmt(r.nc),s:r=>r.nc},
   {h:'区间视频',num:1,f:r=>fmt(r.nv),s:r=>r.nv},
   {h:'区间播放',num:1,f:r=>fmt(r.views),s:r=>r.views},
   {h:'区间收益($)',num:1,f:r=>usd(r.rev),s:r=>r.rev||0},
   {h:'单视频均播放',num:1,f:r=>fmt(r.avg),s:r=>r.avg},
   {h:'频道均播放',num:1,f:r=>fmt(r.nc?Math.round(r.views/r.nc):0),s:r=>r.nc?r.views/r.nc:0},
   {h:'点赞率',num:1,f:r=>pct(r.likes,r.views),s:r=>r.views?r.likes/r.views:0,csv:r=>pctNum(r.likes,r.views)},
 ],opArr,{pageSize:25,exportName:'operators'});

 baseFch=fch; baseFvid=fvid;
 buildLocalFilters();   // 频道维度/Top视频 的局部筛选下拉随平台刷新
 renderChTable();
 renderVidTable();
 vOptions();  // 单视频下拉随平台/发布日期筛选刷新
 if(showRev) rvOptions();  // 单频道收益下拉随平台/日期刷新
}

// 频道维度表(局部:负责人 + 顶部的平台/日期)
function renderChTable(){
 const rows=baseFch.filter(c=>chTblOps.size===0||chTblOps.has(c.operator));
 makeTable(document.getElementById('chTable'),[
   {h:'平台',f:r=>tag(r.platform),s:r=>r.platform},
   {h:'负责人',f:r=>r.operator||'<span class=muted>—</span>',s:r=>r.operator||''},
   {h:'频道',f:r=>`<a href="${r.platform==='YouTube'?'https://youtube.com/channel/'+r.channel_id:'https://www.dailymotion.com/'+r.channel_id}" target=_blank>${r.title}</a>`,s:r=>r.title},
   {h:'订阅/粉丝',num:1,f:r=>fmt(r.subscribers),s:r=>r.subscribers||0},
   {h:'总播放(累计)',num:1,f:r=>fmt(r.total_views),s:r=>r.total_views||0},
   {h:'视频数(总)',num:1,f:r=>fmt(r.videos_total),s:r=>r.videos_total||0},
   {h:'区间视频',num:1,f:r=>fmt(r._n),s:r=>r._n},
   {h:'区间播放',num:1,f:r=>fmt(r._views),s:r=>r._views},
   {h:'区间收益($)',num:1,f:r=>r.platform==='YouTube'?usd(r._rev):'<span class=muted>—</span>',s:r=>r._rev||0},
   {h:'完播率',num:1,f:r=>r.platform==='YouTube'&&r._compl!=null?r._compl.toFixed(1)+'%':'<span class=muted>—</span>',s:r=>r._compl||0,csv:r=>r._compl!=null?r._compl.toFixed(2):''},
   {h:'平均观看时长',num:1,f:r=>r.platform==='YouTube'&&r._avd!=null?dur(r._avd):'<span class=muted>—</span>',s:r=>r._avd||0,csv:r=>r._avd!=null?Math.round(r._avd):''},
   {h:'互动率',num:1,f:r=>r.platform==='YouTube'&&r._eng!=null?r._eng.toFixed(2)+'%':'<span class=muted>—</span>',s:r=>r._eng||0,csv:r=>r._eng!=null?r._eng.toFixed(2):''},
   {h:'RPM($)',num:1,f:r=>r.platform==='YouTube'&&r._rpm!=null?'$'+r._rpm.toFixed(2):'<span class=muted>—</span>',s:r=>r._rpm||0,csv:r=>r._rpm!=null?r._rpm.toFixed(2):''},
   {h:'区间新增订阅',num:1,f:r=>r.platform==='YouTube'?fmt(r._subs):'<span class=muted>—</span>',s:r=>r._subs||0},
   {h:'区间均播放',num:1,f:r=>fmt(r._avg),s:r=>r._avg},
   {h:'点赞率',num:1,f:r=>pct(r._likes,r._views),s:r=>r._views?r._likes/r._views:0,csv:r=>pctNum(r._likes,r._views)},
   {h:'评论率',num:1,f:r=>pct(r._comments,r._views),s:r=>r._views?r._comments/r._views:0,csv:r=>pctNum(r._comments,r._views)},
 ],rows.slice().sort((a,b)=>b._views-a._views),{pageSize:25,exportName:'channels'});
}

// Top视频表(局部:负责人 + 频道 + 顶部的平台/日期)
function renderVidTable(){
 const rows=baseFvid.filter(v=>(vidTblOps.size===0||vidTblOps.has(v.operator))&&(vidTblCh==='all'||key(v)===vidTblCh));
 makeTable(document.getElementById('vidTable'),[
   {h:'平台',f:r=>tag(r.platform),s:r=>r.platform},
   {h:'负责人',f:r=>r.operator||'<span class=muted>—</span>',s:r=>r.operator||''},
   {h:'频道',f:r=>r.channel_title,s:r=>r.channel_title},
   {h:'视频',f:r=>`<a href="${r.url}" target=_blank>${r.video_title}</a>`,s:r=>r.video_title},
   {h:'发布',f:r=>(r.published_at||'').slice(0,10),s:r=>r.published_at||''},
   {h:'时长',num:1,f:r=>r.duration,s:r=>r.duration_sec},
   {h:'播放',num:1,f:r=>fmt(r.views),s:r=>r.views||0},
   {h:'收益($)',num:1,f:r=>{const s=VS[r.video_id];return s&&r.platform==='YouTube'?usd(s[0]):'<span class=muted>—</span>';},s:r=>{const s=VS[r.video_id];return s?s[0]:0;}},
   {h:'完播率',num:1,f:r=>{const s=VS[r.video_id];return s&&s[1]?s[1].toFixed(1)+'%':'<span class=muted>—</span>';},s:r=>{const s=VS[r.video_id];return s?s[1]:0;}},
   {h:'平均观看时长',num:1,f:r=>{const s=VS[r.video_id];return s&&s[2]?dur(s[2]):'<span class=muted>—</span>';},s:r=>{const s=VS[r.video_id];return s?s[2]:0;}},
   {h:'互动率',num:1,f:r=>{const s=VS[r.video_id];return s&&s[3]?((s[4]+s[5]+s[6])/s[3]*100).toFixed(2)+'%':'<span class=muted>—</span>';},s:r=>{const s=VS[r.video_id];return s&&s[3]?(s[4]+s[5]+s[6])/s[3]:0;}},
   {h:'点赞',num:1,f:r=>fmt(r.likes),s:r=>r.likes||0},
   {h:'评论',num:1,f:r=>fmt(r.comments),s:r=>r.comments||0},
   {h:'点赞率',num:1,f:r=>pct(r.likes,r.views),s:r=>r.views?(r.likes||0)/r.views:0,csv:r=>pctNum(r.likes,r.views)},
 ],rows.slice().sort((a,b)=>(b.views||0)-(a.views||0)),{pageSize:25,exportName:'videos'});
}

// 局部筛选下拉:负责人(两表)+ 频道(仅Top视频),随平台刷新、保留仍有效的选择
function buildLocalFilters(){
 const groups=platform==='all'?['YouTube','Dailymotion']:[platform];
 const set=new Set();
 CH.forEach(c=>{if(groups.includes(c.platform)&&c.operator)set.add(c.operator);});
 const ops=[...set].sort((a,b)=>a==='未分配'?1:b==='未分配'?-1:a.localeCompare(b,'zh'));
 buildMultiSel('chOpMs',ops,chTblOps,renderChTable);
 buildMultiSel('vidOpMs',ops,vidTblOps,renderVidTable);
 let chHtml='<option value="all">全部频道</option>';
 groups.forEach(p=>{
   const list=CH.filter(c=>c.platform===p).slice().sort((a,b)=>a.title.localeCompare(b.title,'zh'));
   if(!list.length)return;
   chHtml+=`<optgroup label="${p}">`+list.map(c=>`<option value="${key(c)}">${c.title}</option>`).join('')+'</optgroup>';
 });
 const vc=document.getElementById('vidTblCh');
 if(!(vidTblCh==='all'||CH.some(c=>key(c)===vidTblCh&&groups.includes(c.platform))))vidTblCh='all';
 vc.innerHTML=chHtml; vc.value=vidTblCh;
}

// 多选下拉(selSet 为空=全部);随平台重建,剔除失效项
function buildMultiSel(wrapId, options, selSet, onChange){
 const wrap=document.getElementById(wrapId);
 const btn=wrap.querySelector('.ms-btn'), panel=wrap.querySelector('.ms-panel');
 [...selSet].forEach(v=>{if(!options.includes(v))selSet.delete(v);});
 const refresh=()=>btn.textContent=`${btn.dataset.label}:${selSet.size===0?'全部':selSet.size+'项'} ▾`;
 panel.innerHTML='<label class=row><input type=checkbox class=ms-all '+(selSet.size===0?'checked':'')+'> 全部</label><hr>'
   +options.map(o=>`<label class=row><input type=checkbox value="${o}" ${selSet.has(o)?'checked':''}> ${o}</label>`).join('');
 panel.querySelector('.ms-all').onchange=()=>{selSet.clear();
   panel.querySelectorAll('input[value]').forEach(cb=>cb.checked=false);
   panel.querySelector('.ms-all').checked=true; refresh(); onChange();};
 panel.querySelectorAll('input[value]').forEach(cb=>cb.onchange=()=>{
   cb.checked?selSet.add(cb.value):selSet.delete(cb.value);
   panel.querySelector('.ms-all').checked=selSet.size===0; refresh(); onChange();});
 refresh();
}

const pctNum=(a,b)=>(a==null||!b)?'':(a/b*100).toFixed(2);
function exportCSV(cols,rows,name){
 const esc=v=>{v=(v==null?'':String(v));return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;};
 const head=cols.map(c=>esc(c.h)).join(',');
 const body=rows.map(r=>cols.map(c=>esc(c.csv?c.csv(r):c.s(r))).join(',')).join('\n');
 const blob=new Blob(['﻿'+head+'\n'+body],{type:'text/csv;charset=utf-8'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);
 a.download=name+'_'+new Date().toISOString().slice(0,10)+'.csv';a.click();URL.revokeObjectURL(a.href);
}
function buildInsights(fch,fvid){
 if(!fvid.length) return ['当前筛选条件下无数据。'];
 const B=[];
 const tv=fvid.reduce((s,v)=>s+(v.views||0),0);
 const tl=fvid.reduce((s,v)=>s+(v.likes||0),0);
 // 1) 总量 + 单视频均播放
 B.push(`当前共 <b>${fch.length}</b> 个频道、<b>${fvid.length}</b> 条视频,总播放 <b>${wan(tv)}</b>,单视频平均播放 <b>${wan(tv/fvid.length)}</b>。`);
 // 1.5) 收益维度(仅 YouTube 有数据时)
 const totRev=fch.reduce((s,c)=>s+(c._rev||0),0);
 if(platform!=='Dailymotion'&&totRev>0){
   const rc=fch.filter(c=>(c._rev||0)>0).sort((a,b)=>b._rev-a._rev);
   const orev={}; fch.forEach(c=>{if(c.operator&&c._rev)orev[c.operator]=(orev[c.operator]||0)+c._rev;});
   const oa=Object.entries(orev).sort((a,b)=>b[1]-a[1]);
   let s=`区间预估收益合计 <b>${usd(totRev)}</b>`;
   if(rc[0]) s+=`,收益最高频道 <b>${rc[0].title}</b>(${usd(rc[0]._rev)})`;
   if(rc.length>=3) s+=`,Top3 频道贡献 <b>${(rc.slice(0,3).reduce((x,c)=>x+c._rev,0)/totRev*100).toFixed(0)}%</b>`;
   B.push(s+'。');
   if(oa.length) B.push(`收益按负责人:${oa.slice(0,4).map(([k,v])=>`${k} <b>${usd(v)}</b>`).join(';')}${oa.length>4?' 等':''}。`);
 }
 // 2) 平台对比(仅"全部"时)
 const plats=['YouTube','Dailymotion'].map(p=>{const vd=fvid.filter(v=>v.platform===p);
   const vv=vd.reduce((s,v)=>s+(v.views||0),0);
   return {p,nc:fch.filter(c=>c.platform===p).length,nv:vd.length,vv,avg:vd.length?vv/vd.length:0};}).filter(x=>x.nv>0);
 if(plats.length===2){const a=[...plats].sort((x,y)=>y.avg-x.avg),hi=a[0],lo=a[1];
   const mult=lo.avg?(hi.avg/lo.avg):0;
   B.push(`平台对比:${hi.p} ${hi.nc} 频道/${hi.nv} 视频/${wan(hi.vv)} 播放(单视频均 <b>${wan(hi.avg)}</b>),${lo.p} ${lo.nc} 频道/${lo.nv} 视频/${wan(lo.vv)} 播放(单视频均 ${wan(lo.avg)})。<b>${hi.p} 单视频效率领先,是 ${lo.p} 的 ${mult.toFixed(1)} 倍</b>。`);}
 // 3) 头部集中度
 const sc=fch.slice().sort((x,y)=>y._views-x._views), totCh=sc.reduce((s,c)=>s+c._views,0)||1;
 if(sc.length>=3){const t3=sc.slice(0,3);
   B.push(`播放高度集中在头部:Top3 频道 <b>${t3.map(c=>c.title).join('、')}</b> 合计占总播放 <b>${(t3.reduce((s,c)=>s+c._views,0)/totCh*100).toFixed(0)}%</b>。`);}
 // 4) 单条最高 + 发布量vs效率
 const tvid=fvid.slice().sort((x,y)=>(y.views||0)-(x.views||0))[0];
 if(tvid) B.push(`单条播放最高:《${tvid.video_title}》— ${tvid.channel_title},<b>${wan(tvid.views)}</b>(${(tvid.published_at||'').slice(0,10)})。`);
 const pro=fch.slice().sort((x,y)=>y._n-x._n)[0];
 if(pro&&pro._n>0) B.push(`发布最勤:${pro.title} 区间内 <b>${pro._n}</b> 条,单视频均播放 ${wan(pro._avg)} — 发布量高 ≠ 单条效率高,可对照"分日播放"看产出质量。`);
 // 5) 互动
 const eng=tv?(tl/tv*100):0;
 const cand=fch.filter(c=>c._views>=Math.max(2000,tv*0.01));
 const be=cand.slice().sort((x,y)=>(y._likes/(y._views||1))-(x._likes/(x._views||1)))[0];
 let s=`整体点赞率 <b>${eng.toFixed(2)}%</b>`;
 if(be) s+=`;有量级频道里互动最高的是 <b>${be.title}</b>(${(be._likes/(be._views||1)*100).toFixed(2)}%)`;
 B.push(s+'。');
 // 运营人效(按负责人;跨平台不强行算倍数)
 const opm={}; fvid.forEach(v=>{if(v.operator&&v.operator!=='未分配'){const o=opm[v.operator]=opm[v.operator]||{nv:0,vv:0,plat:v.platform};o.nv++;o.vv+=v.views||0;}});
 const oa=Object.entries(opm).map(([k,o])=>({op:k,plat:o.plat,nv:o.nv,vv:o.vv,avg:o.nv?o.vv/o.nv:0})).sort((a,b)=>b.avg-a.avg);
 if(oa.length>=2){const hi=oa[0],lo=oa[oa.length-1], sameP=oa.every(o=>o.plat===oa[0].plat);
   const top=oa.slice(0,4).map(o=>`${o.op} 单视频均 <b>${wan(o.avg)}</b>`).join(';');
   B.push(`运营人效:${top}${oa.length>4?' 等':''}。<b>${hi.op} 单视频效率最高</b>${sameP&&lo.avg?`,是 ${lo.op} 的 ${(hi.avg/lo.avg).toFixed(1)} 倍`:''}。`);}
 return B;
}
function makeTable(el,cols,rows,opts){
 opts=opts||{}; let pageSize=opts.pageSize||25, page=1, asc={}, data=rows.slice();
 const bar=document.createElement('div'); bar.className='tbar';
 bar.innerHTML=`<button class="btn" data-act=export>⬇ 导出 CSV(全部 ${data.length} 条)</button>`
   +`<span class=pager><button class="btn" data-act=prev>‹ 上一页</button>`
   +`<span class=pageind></span><button class="btn" data-act=next>下一页 ›</button>`
   +` 每页 <select data-act=size><option>25</option><option>50</option><option>100</option></select></span>`;
 const t=document.createElement('table');
 t.innerHTML='<thead><tr>'+cols.map((c,i)=>`<th class="${c.num?'num':''}" data-i=${i}>${c.h}</th>`).join('')+'</tr></thead><tbody></tbody>';
 const tb=t.querySelector('tbody');
 function draw(){const pages=Math.max(1,Math.ceil(data.length/pageSize)); if(page>pages)page=pages; if(page<1)page=1;
   const s=data.slice((page-1)*pageSize,page*pageSize);
   tb.innerHTML=s.map(r=>'<tr>'+cols.map(c=>`<td class="${c.num?'num':''}">${c.f(r)}</td>`).join('')+'</tr>').join('');
   bar.querySelector('.pageind').textContent=` 第 ${page}/${pages} 页(共 ${data.length} 条) `;}
 t.querySelectorAll('th').forEach((th,i)=>th.onclick=()=>{asc[i]=!asc[i];
   data.sort((a,b)=>{const va=cols[i].s(a),vb=cols[i].s(b);return(va>vb?1:va<vb?-1:0)*(asc[i]?1:-1)});page=1;draw();});
 bar.onclick=e=>{const a=e.target.dataset.act; if(a==='prev'){page--;draw();}
   else if(a==='next'){page++;draw();} else if(a==='export')exportCSV(cols,data,opts.exportName||'export');};
 bar.querySelector('[data-act=size]').onchange=e=>{pageSize=+e.target.value;page=1;draw();};
 el.innerHTML=''; el.appendChild(bar); el.appendChild(t); draw();
}

// 事件
document.getElementById('segPlat').onclick=e=>{if(e.target.tagName!=='BUTTON')return;
 [...e.currentTarget.children].forEach(b=>b.classList.remove('on')); e.target.classList.add('on');
 platform=e.target.dataset.p; render();};
document.getElementById('segMode').onclick=e=>{if(e.target.tagName!=='BUTTON')return;
 [...e.currentTarget.children].forEach(b=>b.classList.remove('on')); e.target.classList.add('on');
 chartMode=e.target.dataset.m; render();};
document.getElementById('dFrom').onchange=e=>{dFrom=e.target.value||DMIN; render();};
document.getElementById('dTo').onchange=e=>{dTo=e.target.value||DMAX; render();};
// 局部筛选只重绘对应的表
document.getElementById('vidTblCh').onchange=e=>{vidTblCh=e.target.value; renderVidTable();};
document.querySelectorAll('.ms-btn').forEach(btn=>btn.onclick=e=>{e.stopPropagation();
 const panel=btn.parentElement.querySelector('.ms-panel'), open=panel.classList.contains('open');
 document.querySelectorAll('.ms-panel.open').forEach(p=>p.classList.remove('open'));
 if(!open)panel.classList.add('open');});
document.addEventListener('click',e=>{document.querySelectorAll('.ms-panel.open').forEach(p=>{
 if(!p.closest('.ms').contains(e.target))p.classList.remove('open');});});
document.getElementById('resetBtn').onclick=()=>{platform='all';chTblOps.clear();vidTblOps.clear();vidTblCh='all';dFrom=DMIN;dTo=DMAX;
 [...document.getElementById('segPlat').children].forEach((b,i)=>b.classList.toggle('on',i===0));
 document.getElementById('dFrom').value=DMIN;document.getElementById('dTo').value=DMAX;
 render();};

// ---- 单视频每日趋势 ----
function vOptions(){
 const q=(document.getElementById('vSearch').value||'').toLowerCase();
 const sel=document.getElementById('vSelect'), cur=sel.value;
 const list=VID.filter(v=>(platform==='all'||v.platform===platform)&&(v.video_title||'').toLowerCase().includes(q))
   .sort((a,b)=>(b.views||0)-(a.views||0)).slice(0,300);
 sel.innerHTML=list.map(v=>`<option value="${v.video_id}">${CRAWL[v.video_id]?'★准 ':''}${(v.views||0).toLocaleString()} ▸ ${v.video_title.slice(0,46)} · ${v.channel_title}</option>`).join('')
   || '<option value="">无匹配视频</option>';
 if([...sel.options].some(o=>o.value===cur)) sel.value=cur;
 else { // 默认优先选有爬虫数据(★准)且历史最多的,否则快照最多的
   let best='',bn=-1;
   for(const o of sel.options){const c=CRAWL[o.value]; const n=c?1000+c.length:(VHIST[o.value]||[]).length; if(n>bn){bn=n;best=o.value;}}
   if(best) sel.value=best;
 }
 drawVid();
}
function drawVid(){
 const id=document.getElementById('vSelect').value;
 let labels, views, delta, hint, isCrawl=false;
 const cr=CRAWL[id];
 if(cr&&cr.length){
   const s=cr.slice().sort((a,b)=>a[0]<b[0]?-1:1);
   labels=s.map(x=>x[0]); views=s.map(x=>x[1]); delta=s.map(x=>x[2]);
   hint='★ 爬虫口径:Studio 准数 + 真实当日新增 + 历史'; isCrawl=true;
 } else {
   const s=(VHIST[id]||[]).slice().sort((a,b)=>a[0]<b[0]?-1:1);
   labels=s.map(x=>x[0]); views=s.map(x=>x[1]);
   delta=views.map((v,i)=>i===0?null:v-views[i-1]);
   hint=s.length<2?`公开口径·暂仅 ${s.length} 天快照,趋势将逐日生长`:'公开 API 口径(偏低;此视频不在爬虫覆盖内)';
 }
 setChart('cVid',{data:{labels,datasets:[
   {type:'line',label:'累计播放',data:views,borderColor:'#5bd1a0',backgroundColor:'rgba(91,209,160,.15)',fill:true,tension:.35,pointRadius:3,yAxisID:'y'},
   {type:'bar',label:'当日新增',data:delta,backgroundColor:'rgba(91,157,255,.7)',yAxisID:'y1'}
 ]},options:{plugins:{legend:{labels:{color:'#8b929c',boxWidth:12}},title:{display:!!hint,text:hint,color:isCrawl?'#5bd1a0':'#f7b955',font:{size:13}}},
   scales:{x:{ticks:axc},y:{position:'left',ticks:axc,grid:grd,title:{display:true,text:'累计播放',color:'#8b929c'}},
   y1:{position:'right',ticks:axc,grid:{drawOnChartArea:false},title:{display:true,text:'当日新增',color:'#8b929c'}}}}});
}
document.getElementById('vSearch').oninput=vOptions;
document.getElementById('vSelect').onchange=drawVid;

// ---- 单频道每日收益趋势(仅 YouTube) ----
function rvRange(cid){ return (REV[cid]||[]).filter(a=>a[0]>=dFrom&&a[0]<=dTo); }
function rvOptions(){
 const q=(document.getElementById('rvSearch').value||'').toLowerCase();
 const sel=document.getElementById('rvSelect'), cur=sel.value;
 const list=CH.filter(c=>c.platform==='YouTube'&&(c.title||'').toLowerCase().includes(q))
   .map(c=>({c,rev:rvRange(c.channel_id).reduce((s,a)=>s+a[1],0)}))
   .sort((a,b)=>b.rev-a.rev);
 sel.innerHTML=list.map(x=>`<option value="${x.c.channel_id}">${usd(x.rev)} ▸ ${x.c.title}</option>`).join('')
   || '<option value="">无匹配频道</option>';
 if([...sel.options].some(o=>o.value===cur)) sel.value=cur;
 drawRevCh();
}
function drawRevCh(){
 const id=document.getElementById('rvSelect').value;
 const s=rvRange(id).slice().sort((a,b)=>a[0]<b[0]?-1:1);
 const labels=s.map(x=>x[0]), data=s.map(x=>+Number(x[1]).toFixed(2));
 const tot=data.reduce((a,b)=>a+b,0);
 setChart('cRevCh',{type:'line',data:{labels,datasets:[{label:'日预估收益($)',data,
   borderColor:'#5bd1a0',backgroundColor:'rgba(91,209,160,.15)',fill:true,tension:.3,pointRadius:2}]},
   options:{plugins:{legend:{labels:{color:'#8b929c',boxWidth:12}},
     title:{display:true,text:labels.length?`区间合计 ${usd(tot)}`:'该频道区间内无收益数据',color:'#5bd1a0',font:{size:13}}},
   scales:{x:{ticks:axc},y:{ticks:axc,grid:grd,title:{display:true,text:'日预估收益($)',color:'#8b929c'}}}}});
}
document.getElementById('rvSearch').oninput=rvOptions;
document.getElementById('rvSelect').onchange=drawRevCh;

// init
document.getElementById('dFrom').value=DMIN; document.getElementById('dFrom').min=DMIN; document.getElementById('dFrom').max=DMAX;
document.getElementById('dTo').value=DMAX; document.getElementById('dTo').min=DMIN; document.getElementById('dTo').max=DMAX;
render();
</script></body></html>"""

if __name__ == "__main__":
    main()
