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
        "video_title": r["video_title"], "published_at": r.get("published_at", ""),
        "duration": r.get("duration", ""), "duration_sec": to_int(r.get("duration_sec")) or 0,
        "views": to_int(r.get("views")), "likes": to_int(r.get("likes")), "comments": to_int(r.get("comments")),
        "url": r.get("url", ""),
    } for r in vd]

    dates = sorted(v["published_at"][:10] for v in videos if v.get("published_at"))
    dmin = dates[0] if dates else "2020-01-01"
    dmax = dates[-1] if dates else datetime.date.today().isoformat()

    # 每日快照历史(逐日累积,API 无法回填)
    hist = []
    hp = HERE / "history" / "daily.csv"
    if hp.exists():
        for r in csv.DictReader(open(hp)):
            hist.append({"date": r["date"], "platform": r["platform"], "channel_id": r["channel_id"],
                         "total_views": to_int(r.get("total_views"))})

    libf = HERE / "chart.umd.min.js"
    chartjs = ("<script>"+libf.read_text(encoding="utf-8")+"</script>") if libf.exists() \
              else '<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>'

    html = (TEMPLATE
            .replace("__CHARTJS__", chartjs)
            .replace("__GEN__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__DMIN__", dmin).replace("__DMAX__", dmax)
            .replace("__CH__", json.dumps(channels, ensure_ascii=False))
            .replace("__VID__", json.dumps(videos, ensure_ascii=False))
            .replace("__HIST__", json.dumps(hist, ensure_ascii=False)))
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
 .btn{background:#262a33;color:#cfd3da;border:1px solid #313742;border-radius:6px;padding:7px 12px;cursor:pointer;font-size:13px}
 .panel{position:absolute;top:64px;left:14px;z-index:20;background:#1a1d24;border:1px solid #313742;border-radius:10px;padding:12px;width:340px;max-height:360px;overflow:auto;box-shadow:0 8px 24px rgba(0,0,0,.5);display:none}
 .panel.open{display:block}
 .panel input[type=search]{width:100%;box-sizing:border-box;background:#0f1115;color:#e6e8eb;border:1px solid #313742;border-radius:6px;padding:6px 8px;margin-bottom:8px}
 .panel .grp{color:#8b929c;font-size:11px;margin:8px 0 4px;text-transform:uppercase}
 .panel .row{display:flex;align-items:center;gap:6px;padding:3px 2px;font-size:13px}
 .panel .row label{color:#e6e8eb;margin:0;cursor:pointer;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}
 .kpi{background:#1a1d24;border:1px solid #262a33;border-radius:10px;padding:16px}
 .kpi .v{font-size:24px;font-weight:700} .kpi .l{color:#8b929c;font-size:12px;margin-top:4px}
 .card{background:#1a1d24;border:1px solid #262a33;border-radius:10px;padding:16px;margin-bottom:20px}
 .card h2{font-size:15px;margin:0 0 12px}
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
 <button class="btn" id="chBtn">频道 ▾</button>
 <button class="btn" id="resetBtn">重置</button>
 <div class="panel" id="chPanel">
   <input type="search" id="chSearch" placeholder="搜索频道名…">
   <div style="display:flex;gap:8px;margin-bottom:6px">
     <button class="btn" id="selAll" style="flex:1">全选(可见)</button>
     <button class="btn" id="selNone" style="flex:1">清空(可见)</button>
   </div>
   <div id="chList"></div>
 </div>
</div>

<div class="kpis" id="kpis"></div>
<div class="card grid2">
 <div><h2>各频道订阅/粉丝(累计 · Top20)</h2><canvas id="cSub"></canvas></div>
 <div><h2>各频道区间播放(Top20)</h2><canvas id="cViews"></canvas></div>
</div>
<div class="card">
 <div style="display:flex;align-items:center;gap:12px;margin-bottom:6px;flex-wrap:wrap">
   <h2 style="margin:0">分日播放(按发布日期)</h2>
   <span class="seg" id="segMode"><button data-m="channel" class="on">Top10 频道</button><button data-m="video">Top10 视频</button></span>
 </div>
 <div class="sub" style="margin-bottom:10px">按视频发布日期聚合的播放量。<b>频道模式</b>:播放最高的 Top10 频道各一条日线;<b>视频模式</b>:Top10 单视频的播放量。用上方"平台/频道/发布日期"筛选可换一批。</div>
 <canvas id="cDaily" style="max-height:360px"></canvas>
</div>
<div class="card"><h2>频道维度</h2><div id="chTable"></div></div>
<div class="card"><h2>Top 视频(区间内)</h2><div id="vidTable"></div></div>
</div>
<script>
const CH=__CH__, VID=__VID__, HIST=__HIST__, DMIN="__DMIN__", DMAX="__DMAX__";
const PALETTE=['#5b9dff','#5bd1a0','#f7b955','#e06c75','#b18cff','#56c2d6','#d49bd4','#9aa7b5'];
const fmt=n=>n==null?'<span class=muted>—</span>':Number(n).toLocaleString();
const pct=(a,b)=>(a==null||!b)?'<span class=muted>—</span>':(a/b*100).toFixed(2)+'%';
const key=x=>x.platform+'|'+x.channel_id;
const tag=p=>`<span class="tag ${p==='YouTube'?'yt':'dm'}">${p==='YouTube'?'YT':'DM'}</span>`;
let platform='all', dFrom=DMIN, dTo=DMAX, selected=new Set(CH.map(key)), charts={}, chartMode='channel';

const chPass=c=>(platform==='all'||c.platform===platform)&&selected.has(key(c));
const vidPass=v=>{const d=(v.published_at||'').slice(0,10);
  return (platform==='all'||v.platform===platform)&&selected.has(key(v))&&d>=dFrom&&d<=dTo;};

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

 // KPI
 const sum=(a,k)=>a.reduce((s,x)=>s+(x[k]||0),0);
 document.getElementById('kpis').innerHTML=[
  ['频道数',fch.length],['区间视频数',fvid.length],
  ['总订阅/粉丝(累计)',sum(fch,'subscribers')],['区间播放合计',sum(fvid,'views')],
 ].map(([l,v])=>`<div class=kpi><div class=v>${v.toLocaleString()}</div><div class=l>${l}</div></div>`).join('');

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

 // tables
 makeTable(document.getElementById('chTable'),[
   {h:'平台',f:r=>tag(r.platform),s:r=>r.platform},
   {h:'频道',f:r=>`<a href="${r.platform==='YouTube'?'https://youtube.com/channel/'+r.channel_id:'https://www.dailymotion.com/'+r.channel_id}" target=_blank>${r.title}</a>`,s:r=>r.title},
   {h:'订阅/粉丝',num:1,f:r=>fmt(r.subscribers),s:r=>r.subscribers||0},
   {h:'总播放(累计)',num:1,f:r=>fmt(r.total_views),s:r=>r.total_views||0},
   {h:'视频数(总)',num:1,f:r=>fmt(r.videos_total),s:r=>r.videos_total||0},
   {h:'区间视频',num:1,f:r=>fmt(r._n),s:r=>r._n},
   {h:'区间播放',num:1,f:r=>fmt(r._views),s:r=>r._views},
   {h:'区间均播放',num:1,f:r=>fmt(r._avg),s:r=>r._avg},
   {h:'点赞率',num:1,f:r=>pct(r._likes,r._views),s:r=>r._views?r._likes/r._views:0,csv:r=>pctNum(r._likes,r._views)},
   {h:'评论率',num:1,f:r=>pct(r._comments,r._views),s:r=>r._views?r._comments/r._views:0,csv:r=>pctNum(r._comments,r._views)},
 ],fch.slice().sort((a,b)=>b._views-a._views),{pageSize:25,exportName:'channels'});

 makeTable(document.getElementById('vidTable'),[
   {h:'平台',f:r=>tag(r.platform),s:r=>r.platform},
   {h:'频道',f:r=>r.channel_title,s:r=>r.channel_title},
   {h:'视频',f:r=>`<a href="${r.url}" target=_blank>${r.video_title}</a>`,s:r=>r.video_title},
   {h:'发布',f:r=>(r.published_at||'').slice(0,10),s:r=>r.published_at||''},
   {h:'时长',num:1,f:r=>r.duration,s:r=>r.duration_sec},
   {h:'播放',num:1,f:r=>fmt(r.views),s:r=>r.views||0},
   {h:'点赞',num:1,f:r=>fmt(r.likes),s:r=>r.likes||0},
   {h:'评论',num:1,f:r=>fmt(r.comments),s:r=>r.comments||0},
   {h:'点赞率',num:1,f:r=>pct(r.likes,r.views),s:r=>r.views?(r.likes||0)/r.views:0,csv:r=>pctNum(r.likes,r.views)},
 ],fvid.slice().sort((a,b)=>(b.views||0)-(a.views||0)),{pageSize:25,exportName:'videos'});
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

// ---- 频道筛选面板 ----
function buildList(){
 const q=(document.getElementById('chSearch').value||'').toLowerCase();
 const groups=platform==='all'?['YouTube','Dailymotion']:[platform];
 let html='';
 groups.forEach(p=>{
   const list=CH.filter(c=>c.platform===p&&c.title.toLowerCase().includes(q));
   if(!list.length)return;
   html+=`<div class=grp>${p} (${list.length})</div>`;
   list.forEach(c=>{const k=key(c);
     html+=`<div class=row><input type=checkbox data-k="${k}" ${selected.has(k)?'checked':''}><label>${c.title}</label></div>`;});
 });
 const el=document.getElementById('chList'); el.innerHTML=html;
 el.querySelectorAll('input[type=checkbox]').forEach(cb=>cb.onchange=()=>{
   cb.checked?selected.add(cb.dataset.k):selected.delete(cb.dataset.k); updateChBtn(); render();});
}
function visibleKeys(){
 const q=(document.getElementById('chSearch').value||'').toLowerCase();
 const groups=platform==='all'?['YouTube','Dailymotion']:[platform];
 return CH.filter(c=>groups.includes(c.platform)&&c.title.toLowerCase().includes(q)).map(key);
}
function updateChBtn(){const tot=platform==='all'?CH.length:CH.filter(c=>c.platform===platform).length;
 const sel=CH.filter(c=>(platform==='all'||c.platform===platform)&&selected.has(key(c))).length;
 document.getElementById('chBtn').textContent=`频道 ${sel}/${tot} ▾`;}

// 事件
document.getElementById('segPlat').onclick=e=>{if(e.target.tagName!=='BUTTON')return;
 [...e.currentTarget.children].forEach(b=>b.classList.remove('on')); e.target.classList.add('on');
 platform=e.target.dataset.p; buildList(); updateChBtn(); render();};
document.getElementById('segMode').onclick=e=>{if(e.target.tagName!=='BUTTON')return;
 [...e.currentTarget.children].forEach(b=>b.classList.remove('on')); e.target.classList.add('on');
 chartMode=e.target.dataset.m; render();};
document.getElementById('dFrom').onchange=e=>{dFrom=e.target.value||DMIN; render();};
document.getElementById('dTo').onchange=e=>{dTo=e.target.value||DMAX; render();};
document.getElementById('chBtn').onclick=()=>document.getElementById('chPanel').classList.toggle('open');
document.getElementById('chSearch').oninput=buildList;
document.getElementById('selAll').onclick=()=>{visibleKeys().forEach(k=>selected.add(k));buildList();updateChBtn();render();};
document.getElementById('selNone').onclick=()=>{visibleKeys().forEach(k=>selected.delete(k));buildList();updateChBtn();render();};
document.getElementById('resetBtn').onclick=()=>{platform='all';selected=new Set(CH.map(key));dFrom=DMIN;dTo=DMAX;
 [...document.getElementById('segPlat').children].forEach((b,i)=>b.classList.toggle('on',i===0));
 document.getElementById('dFrom').value=DMIN;document.getElementById('dTo').value=DMAX;
 buildList();updateChBtn();render();};
document.addEventListener('click',e=>{const p=document.getElementById('chPanel'),b=document.getElementById('chBtn');
 if(p.classList.contains('open')&&!p.contains(e.target)&&e.target!==b)p.classList.remove('open');});

// init
document.getElementById('dFrom').value=DMIN; document.getElementById('dFrom').min=DMIN; document.getElementById('dFrom').max=DMAX;
document.getElementById('dTo').value=DMAX; document.getElementById('dTo').min=DMIN; document.getElementById('dTo').max=DMAX;
buildList(); updateChBtn(); render();
</script></body></html>"""

if __name__ == "__main__":
    main()
