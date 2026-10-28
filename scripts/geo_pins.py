#!/usr/bin/env python3.15t
"""Pin layer for the die maps (scripts/geo_map.py, scripts/geo_image_overlay.py): device_pins -> embedded JSON + shared CSS/HTML/JS.

  python3.15t scripts/geo_pins.py     # prints counts only
Source: table device_pins (databases/cycloneiv/gx150.db, filled by scripts/pins_register.py), read-only.  Docs: docs/geo-pins.md.
The host page must define: S (let), M, NY, cv, ctx, css(), draw(), vis, grid, setZoom(v), and call pinsDraw() from draw().
"""
import json
import os
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEVICE = "EP4CGX150DF31"
SPECIALS = ["none", "config", "jtag", "clock", "transceiver", "reference", "power", "ground"]


def load_pins(device=DEVICE):
    """-> dict(p=[row...], src=[source dict...], sp=SPECIALS).  Row layout is PIN_ROW in the JS below."""
    path = os.environ.get("PLURIBUS_SQLITE_PATH") or str(REPO / "databases/cycloneiv/gx150.db")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    q = ("select pin,pad_number,bank,side,tile_x,tile_y,z,io_site,io_type,func_names,ibis_net,special,bonded,usage_default,source,conflicts "
         "from device_pins where device=? order by pin")
    rows, srcs, sidx = [], [], {}
    for (pin, pad, bank, side, x, y, z, site, ty, fn, ibis, sp, bonded, usage, src, conf) in con.execute(q, (device,)):
        if src not in sidx:
            sidx[src] = len(srcs)
            srcs.append(json.loads(src))
        rows.append([pin, pad, bank or "", side or "", x, y, z, site or "", ty or "", (json.loads(fn) if fn else None) or [], ibis or "",
                     SPECIALS.index(sp or "none"), 1 if bonded else 0, usage or "", sidx[src], (json.loads(conf) if conf else None) or []])
    con.close()
    if not rows:
        raise SystemExit(f"geo_pins: no device_pins rows for {device}")
    return dict(dev=device, p=rows, src=srcs, sp=SPECIALS)


def data_js(pins):
    return json.dumps(pins, separators=(",", ":"), ensure_ascii=False)


CSS = r"""
:root{--pn0:#374151;--pn1:#d97706;--pn2:#9333ea;--pn3:#dc2626;--pn4:#db2777;--pn5:#16a34a;--pn6:#92400e;--pn7:#6b7280;--bad:#d23a3a}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--pn0:#e5e7eb;--pn1:#fbbf24;--pn2:#c084fc;--pn3:#f87171;--pn4:#f472b6;--pn5:#4ade80;--pn6:#d6a36a;--pn7:#9ca3af;--bad:#ff6b6b}}
:root[data-theme=dark]{--pn0:#e5e7eb;--pn1:#fbbf24;--pn2:#c084fc;--pn3:#f87171;--pn4:#f472b6;--pn5:#4ade80;--pn6:#d6a36a;--pn7:#9ca3af;--bad:#ff6b6b}
#pins input[type=search]{width:100%;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
#pins .cnt{font-variant-numeric:tabular-nums;margin:4px 0}
#pins .res,#pins .nosite{max-height:170px;overflow:auto;border:1px solid var(--line);border-radius:6px;margin-top:4px;font-size:12.5px}
#pins .row{display:flex;gap:6px;align-items:center;padding:1px 6px;cursor:pointer;white-space:nowrap}
#pins .row:hover,#pins .row.on{background:var(--line)}
#pins .row .m{color:var(--mut);overflow:hidden;text-overflow:ellipsis}
#pins .pin{border-top:1px solid var(--line);padding:6px 0}
#pins .pin:first-child{border-top:0}
#pins .pin table td:first-child{color:var(--mut);white-space:nowrap;padding-right:8px}
#pins .pin table td:last-child{text-align:left;word-break:break-word}
#pins .bad{color:var(--bad);font-weight:600}
#pins details{margin-top:2px}#pins summary{cursor:pointer;color:var(--mut)}
#pins .dot{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none;border:2px solid transparent}
#pins .dot.nb{background:transparent!important}
"""

HTML = r"""<div class="card" id="pins"><b>Pins (EP4CGX150DF31)</b>
<div class="cnt" id="pcnt"></div>
<label><input type="checkbox" id="oPins" checked> Pin markers on IO tiles</label>
<label><input type="checkbox" id="oPinLab" checked> Ball labels (zoom in, map zoom 32+)</label>
<div id="pleg" style="margin:4px 0"></div>
<input type="search" id="psearch" placeholder="Ball (AB12) or name (DIFFIO_B1n, CLK7p, DATA0)" aria-label="Search pins">
<div class="res" id="pres" hidden></div>
<div class="note" id="pnote"></div>
<div id="pinsel" style="margin-top:8px"><span class="note">Hover or click an IO tile to list its pins.</span></div>
<b style="display:block;margin-top:10px" id="nshead"></b>
<div class="nosite" id="nosite"></div>
<div class="note">Site coverage grows as more IO builds are registered (scripts/pins_register.py). A pin appears on the map only when its die site is known; the others are listed above with bank and side.</div>
</div>"""

JS = r"""
// ---- pin layer.  row: [ball,pad,bank,side,x,y,z,site,type,funcs,ibis,special,bonded,usage,srcIdx,conflicts]
const PD=__PINDATA__,PR=PD.p,SP=PD.sp;
const PT=new Map();PR.forEach((p,i)=>{if(p[4]!=null){const k=p[4]*1000+p[5];(PT.get(k)||PT.set(k,[]).get(k)).push(i)}});
PT.forEach(a=>a.sort((a,b)=>PR[a][6]-PR[b][6]||PR[a][0].localeCompare(PR[b][0])));
const PSITE=PR.filter(p=>p[4]!=null).length,PCONF=PR.filter(p=>p[15].length).length;
let pinHi=new Set(),pinLock=null,pinHover=null,pinFocus=null;
const pcol=i=>css('--pn'+PR[i][11]);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function pinPos(n,k,lab){ // centre of pin k of n within a tile of S px
 if(lab){const rh=S/4,top=(S-1-rh*n)/2;return [S*.14,top+rh*(k+.5)]}
 if(n<=2){const w=(S-1)/2;return [w*(k+.5),(S-1)/2]}
 const w=(S-1)/2;return [w*((k&1)+.5),w*((k>>1)+.5)]}
function pinsDraw(){
 if(!document.getElementById('oPins').checked||!vis.IO)return;
 const lab=S>=32&&document.getElementById('oPinLab').checked,r=lab?Math.max(2,S*.06):Math.max(1.4,S*.16);
 ctx.textBaseline='middle';
 PT.forEach((a,key)=>{const x=Math.floor(key/1000),y=key%1000,px=M+x*S,py=M+(NY-1-y)*S,n=a.length;
  a.forEach((i,k)=>{const [dx,dy]=pinPos(n,k,lab),cx=px+dx,cy=py+dy,c=pcol(i),p=PR[i];
   ctx.beginPath();ctx.arc(cx,cy,r,0,7);
   if(p[12]){ctx.fillStyle=c;ctx.fill()}else{ctx.strokeStyle=c;ctx.lineWidth=Math.max(1,r*.45);ctx.stroke()}
   if(pinHi.has(i)){ctx.beginPath();ctx.arc(cx,cy,r+3,0,7);ctx.strokeStyle=css('--accent');ctx.lineWidth=2;ctx.stroke()}
   if(lab){const f=Math.min(S/4*.85,(S-dx-r-3)/(.62*p[0].length+.2));ctx.font=`${f}px system-ui,sans-serif`;ctx.fillStyle=css('--fg');ctx.fillText(p[0],cx+r+2,cy)}});
  if(a.some(i=>pinHi.has(i))){ctx.strokeStyle=css('--accent');ctx.lineWidth=2;ctx.strokeRect(px-1,py-1,S+1,S+1)}})}
function pinHtml(i){const p=PR[i],src=PD.src[p[14]];
 const fl=p[9].length?p[9].map(esc).join(', '):'-',cf=p[15];
 let h=`<div class="pin"><b>${esc(p[0])}</b> <span class="dot${p[12]?'':' nb'}" style="background:${pcol(i)};border-color:${pcol(i)}"></span> ${SP[p[11]]}${p[12]?'':' (not bonded)'}<table>`+
  `<tr><td>Pad number</td><td>${p[1]==null?'-':p[1]}</td></tr><tr><td>Bank / side</td><td>${esc(p[2]||'-')} / ${esc(p[3]||'-')}</td></tr>`+
  `<tr><td>Die site</td><td>${p[4]==null?'none yet':`${esc(p[7])} (X${p[4]} Y${p[5]} z${p[6]})`}</td></tr>`+
  `<tr><td>I/O type</td><td>${esc(p[8]||'-')}</td></tr><tr><td>Vendor names</td><td>${fl}</td></tr><tr><td>IBIS net</td><td>${esc(p[10]||'-')}</td></tr>`+
  `<tr><td>Usage default</td><td>${esc(p[13]||'-')}</td></tr></table>`+
  `<details><summary>source fields</summary><table>${Object.keys(src).map(f=>`<tr><td>${f}</td><td>${src[f].map(esc).join(', ')}</td></tr>`).join('')}</table></details>`;
 for(const c of cf)h+=`<div class="bad">conflict in ${esc(c.field)}: ${Object.keys(c.values).map(s=>esc(s)+' = '+esc(JSON.stringify(c.values[s]))).join('; ')}</div>`;
 return h+'</div>'}
function pinPanel(){ // hover wins over lock
 const el=document.getElementById('pinsel'),t=pinHover!=null?pinHover:pinLock;
 if(t==null||(typeof t==='number'&&!PT.has(t))){el.innerHTML='<span class="note">Hover or click an IO tile to list its pins.</span>';return}
 if(typeof t==='object'){el.innerHTML=pinHtml(t.i);return}
 const a=PT.get(t);el.innerHTML=`<b>Tile X${Math.floor(t/1000)} Y${t%1000}</b>: ${a.length} pin${a.length>1?'s':''}`+(pinLock===t&&pinHover==null?' (selected)':'')+a.map(pinHtml).join('')}
function pinTileAt(e){const r=cv.getBoundingClientRect(),sx=cv.width/r.width;
 const x=Math.floor(((e.clientX-r.left)*sx-M)/S),y=NY-1-Math.floor(((e.clientY-r.top)*sx-M)/S),k=x*1000+y;return PT.has(k)?k:null}
cv.addEventListener('mousemove',e=>{const k=pinTileAt(e);if(k!==pinHover){pinHover=k;pinPanel()}});
cv.addEventListener('mouseleave',()=>{pinHover=null;pinPanel()});
cv.addEventListener('click',e=>{const k=pinTileAt(e);pinLock=k;pinPanel()});
// ---- search + lists
const norm=s=>s.toLowerCase();
function pinMatches(q){q=norm(q.trim());if(!q)return[];const ex=[],part=[];
 PR.forEach((p,i)=>{if(norm(p[0])===q)ex.push(i);else if(norm(p[0]).startsWith(q)||p[9].some(f=>norm(f).includes(q))||norm(p[10]).includes(q)||norm(p[7]).includes(q))part.push(i)});
 return ex.concat(part)}
const rowHtml=i=>{const p=PR[i];return `<div class="row" data-i="${i}"><span class="dot${p[12]?'':' nb'}" style="background:${pcol(i)};border-color:${pcol(i)}"></span><b>${esc(p[0])}</b><span class="m">${esc(p[2]||'-')} / ${esc(p[3]||'-')} / ${esc(p[9].join(', ')||SP[p[11]])}${p[4]==null?'':' / X'+p[4]+' Y'+p[5]}</span></div>`};
function renderNoSite(q){const all=PR.map((p,i)=>i).filter(i=>PR[i][4]==null),m=q?new Set(pinMatches(q)):null,l=m?all.filter(i=>m.has(i)):all;
 document.getElementById('nshead').textContent=`no die site yet (${all.length})`+(m?` - ${l.length} match`:'');
 const el=document.getElementById('nosite');el.innerHTML=l.map(rowHtml).join('')||'<div class="row"><span class="m">none</span></div>';
 el.querySelectorAll('.row[data-i]').forEach(r=>r.onclick=()=>pinGo(+r.dataset.i,false))}
function pinGo(i,zoom){const p=PR[i];pinHi=new Set([i]);
 if(p[4]==null){pinHover=null;pinLock=null;document.getElementById('pinsel').innerHTML=pinHtml(i)+'<div class="note">No die site registered for this ball yet: not drawn on the map.</div>';draw();return}
 vis.IO=1;const cb=document.querySelector('[data-k=IO]');if(cb)cb.checked=true;
 pinLock=p[4]*1000+p[5];pinHover=null;if(zoom!==false)setZoom(Math.max(S,40));else draw();
 pinPanel();draw();
 const sc=cv.parentElement,k=cv.getBoundingClientRect().width/cv.width;
 sc.scrollLeft=(M+p[4]*S+S/2)*k-sc.clientWidth/2;sc.scrollTop=(M+(NY-1-p[5])*S+S/2)*k-sc.clientHeight/2;
 const b=cv.getBoundingClientRect();if(b.top<0||b.top>innerHeight)cv.scrollIntoView({block:'center'})}
function pinSearch(go){const q=document.getElementById('psearch').value,m=pinMatches(q),el=document.getElementById('pres'),nt=document.getElementById('pnote');
 renderNoSite(q);
 if(!q.trim()){pinHi=new Set();el.hidden=true;nt.textContent='';draw();return}
 const onmap=m.filter(i=>PR[i][4]!=null);pinHi=new Set(onmap);
 el.hidden=false;el.innerHTML=m.slice(0,60).map(rowHtml).join('')||'<div class="row"><span class="m">no match</span></div>';
 el.querySelectorAll('.row[data-i]').forEach(r=>r.onclick=()=>pinGo(+r.dataset.i));
 nt.textContent=`${m.length} match${m.length==1?'':'es'}: ${onmap.length} on the map (ringed), ${m.length-onmap.length} without die site`+(m.length>60?' (first 60 listed)':'');
 if(go&&m.length)pinGo(onmap.length?onmap[0]:m[0]);else draw()}
(function(){const cnt=document.getElementById('pcnt'),bon=PR.filter(p=>p[12]).length;
 cnt.innerHTML=`<b>${PR.length}</b> pins: <b>${PSITE}</b> with die site, <b>${PR.length-PSITE}</b> without. Bonded ${bon}. Conflicts flagged ${PCONF}.`;
 const n=SP.map(()=>[0,0]);PR.forEach(p=>{n[p[11]][0]++;if(p[4]!=null)n[p[11]][1]++});
 document.getElementById('pleg').innerHTML=SP.map((s,i)=>`<div style="display:flex;gap:6px;align-items:center;font-size:12.5px"><span class="dot" style="background:var(--pn${i});border-color:var(--pn${i})"></span>${s}<span style="margin-left:auto;color:var(--mut)">${n[i][1]} / ${n[i][0]}</span></div>`).join('')+
  `<div style="font-size:12.5px;margin-top:2px"><span class="dot nb" style="border-color:var(--fg)"></span> hollow = not bonded. Right column: with site / total.</div>`;
 const q=document.getElementById('psearch');q.oninput=()=>pinSearch(false);q.onkeydown=e=>{if(e.key==='Enter')pinSearch(true)};
 ['oPins','oPinLab'].forEach(id=>document.getElementById(id).onchange=draw);renderNoSite('')})();
"""


def inject(page, pins):
    """Fill the __PINS_CSS__ / __PINS_HTML__ / __PINS_JS__ markers of a host page."""
    js = JS.replace("__PINDATA__", data_js(pins))
    return page.replace("/*__PINS_CSS__*/", CSS).replace("<!--__PINS_HTML__-->", HTML).replace("/*__PINS_JS__*/", js)


if __name__ == "__main__":
    d = load_pins()
    p = d["p"]
    print(f"{d['dev']}: {len(p)} pins, {sum(r[4] is not None for r in p)} with die site, {sum(bool(r[15]) for r in p)} with conflicts, {len(data_js(d))/1e3:.0f} kB JSON")
