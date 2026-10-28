#!/usr/bin/env python3.15t
"""Package view: BGA ball grid of one device/package from device_pins -> tmp/geo/package_map.html (self-contained, no network).

  python3.15t scripts/geo_package.py [--db PATH] [--device EP4CGX150] [--package DF31]
Rows/columns come from the ball names; every matrix position is drawn, positions with no row in the table are marked.
Bottom (ball side) and mirrored Top view; die inset.  Data: scripts/geo_pins.py (device_pins, read-only).  Docs: docs/geo-pins.md.
"""
import argparse
import json
import os
import re
import sqlite3
import string
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEO = REPO / "tmp/geo"
sys.path.insert(0, str(REPO / "scripts"))
import geo_pins  # noqa: E402

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Package ball map</title>
<style>
:root{--bg:#fbfbfa;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#d9d8d3;--accent:#2a5bd7;--bkl:42%}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#17181a;--fg:#e8e8e4;--mut:#9a9a94;--card:#202225;--line:#38393c;--accent:#7fa2ff;--bkl:62%}}
:root[data-theme=dark]{--bg:#17181a;--fg:#e8e8e4;--mut:#9a9a94;--card:#202225;--line:#38393c;--accent:#7fa2ff;--bkl:62%}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;padding:16px}
h1{font-size:20px;margin:0 0 2px}p.sub{margin:0 0 12px;color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin-bottom:12px}
fieldset{border:0;padding:0;margin:0 0 10px}legend{font-weight:600;margin-bottom:4px}
label{display:flex;gap:6px;align-items:center;margin:2px 0;cursor:pointer}
.note{color:var(--mut);font-size:12px;margin-top:6px}
table{border-collapse:collapse;width:100%;font-size:13px}td{padding:1px 0;vertical-align:top}td:first-child{color:var(--mut);white-space:nowrap;padding-right:8px}
.lg{display:flex;gap:6px;align-items:center;font-size:12.5px;margin:1px 0}.lg .n{margin-left:auto;color:var(--mut);font-variant-numeric:tabular-nums}
.dot{width:11px;height:11px;border-radius:50%;display:inline-block;flex:none;border:2px solid}
.bad{color:var(--bad);font-weight:600}
input[type=search]{width:100%;padding:4px 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
.res{max-height:170px;overflow:auto;border:1px solid var(--line);border-radius:6px;margin-top:4px;font-size:12.5px}
.row{display:flex;gap:6px;align-items:center;padding:1px 6px;cursor:pointer;white-space:nowrap}.row:hover{background:var(--line)}.row .m{color:var(--mut);overflow:hidden;text-overflow:ellipsis}
svg#pk{display:block;margin:0 auto;max-width:100%;height:auto;user-select:none}
svg text{fill:var(--mut);font:9px system-ui,sans-serif}
#tip{position:fixed;pointer-events:none;z-index:5;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:3px 8px;font-size:12px;box-shadow:0 2px 8px #0003;display:none}
a{color:var(--accent)}
/*__PINS_CSS__*/
</style></head><body>
<h1 id="h1"></h1>
<p class="sub">Every ball of the package at its matrix position, from the device pin table. Hover a ball for its card, click or tap to select.</p>
<div class="wrap">
<div><div class="card" style="overflow:auto"><div id="vlabel" style="font-weight:600;text-align:center"></div><div class="note" id="vhint" style="text-align:center;margin:0 0 4px"></div>
<svg id="pk" role="img" aria-label="Package ball grid"></svg></div></div>
<aside id="side">
<!--__PANEL_BAR__-->
<details class="pnl" id="pn-ctl" open><summary>View, colour and size</summary><div class="pb">
<fieldset><legend>View</legend>
<label><input type="radio" name="view" value="b" checked> Bottom (ball side, as seen from the PCB side)</label>
<label><input type="radio" name="view" value="t"> Top (package lid side, as seen from above)</label></fieldset>
<fieldset><legend>Colour by</legend>
<label><input type="radio" name="col" value="role" checked> Role</label>
<label><input type="radio" name="col" value="bank"> I/O bank</label>
<label><input type="checkbox" id="oBank" checked> Highlight all balls of the hovered or selected ball's bank</label>
<label><input type="checkbox" id="oPair" checked> Link differential pair partners</label></fieldset>
<fieldset><legend>Map size</legend>
<label>Size <input type="range" id="zoom" min="30" max="100" value="58" aria-label="Map size"> <span id="zv" style="min-width:3em;text-align:right"></span></label>
<div style="display:flex;gap:6px;align-items:center"><button type="button" id="fitbtn">Fit</button><span class="note" style="margin:0">Fit = full window. Default is about 58 % of it.</span></div></fieldset>
</div></details>
<details class="pnl" id="pn-card" open><summary>Pin card</summary><div class="pb"><div id="card"><span class="note">Hover or click a ball.</span></div></div></details>
<details class="pnl" id="pn-find" open><summary>Search</summary><div class="pb">
<input type="search" id="q" placeholder="Ball (AB12), name (DIFFIO_B1n, CLK7p) or net" aria-label="Search balls">
<div class="res" id="res" hidden></div><div class="note" id="qn"></div></div></details>
<details class="pnl" id="pn-die" open><summary>Die position</summary><div class="pb"><svg id="die" viewBox="0 0 200 160" style="width:100%;max-width:300px;display:block;margin:0 auto" role="img" aria-label="Die inset"></svg>
<fieldset style="margin-top:6px"><label><input type="radio" name="dv" value="t" checked> Die seen from the top surface (as the die map)</label>
<label><input type="radio" name="dv" value="f"> Seen from the bottom (flip-chip, bumps side): mirrored</label></fieldset>
<div class="note" id="dnote"></div></div></details>
<details class="pnl" id="pn-leg" open><summary>Legend and filters</summary><div class="pb"><div id="cnt"></div>
<fieldset><legend>Roles (right: balls)</legend><div id="froles"></div></fieldset>
<fieldset><legend>I/O banks</legend><div id="fbanks"></div></fieldset>
<fieldset><legend>Die site</legend><div id="fsite"></div></fieldset>
<div class="note">Filled = bonded, hollow = not bonded. Dashed = matrix position with no pin in the table. Centre dot = die site known.</div></div></details>
<details class="pnl" id="pn-notes"><summary>Notes</summary><div class="pb"><div class="note" style="margin:0" id="notes"></div></div></details>
</aside></div>
<div id="tip"></div>
<script>
const D=__DATA__,PR=D.p,SP=D.sp,N=D.cols,R=D.rows.length;
const ROLE=["user I/O","config","JTAG","clock","transceiver","reference","power","ground","NC"];
const SITE=["with die site","no site yet","no site expected (supply / NC)"];
const siteOf=p=>p[4]!=null?0:(p[16]?1:2);
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function stGet(k){try{return localStorage.getItem('geo-pkg:'+k)}catch(e){return null}}
function stSet(k,v){try{localStorage.setItem('geo-pkg:'+k,v)}catch(e){}}
const PK=22,L=34,W=N*PK+2*L,H=R*PK+2*L,NS='http://www.w3.org/2000/svg';
const at=new Map();PR.forEach((p,i)=>{const m=/^([A-Z]+)(\d+)$/.exec(p[0]);at.set(D.rows.indexOf(m[1])*100+(+m[2]-1),i)});
const BK=[...new Set(PR.map(p=>p[2]))].sort((a,b)=>(a===''?1:0)-(b===''?1:0)||a.localeCompare(b,undefined,{numeric:true}));
const bcol=b=>b===''?css('--mut'):`hsl(${Math.round(360*BK.indexOf(b)/BK.length)} 65% var(--bkl))`;
// differential pairs: vendor names ending p/n after a digit or underscore, same base, both present
const PAIR=new Map(),pb=new Map();
PR.forEach((p,i)=>p[9].forEach(f=>{const m=/^(.*[0-9_])([pPnN])$/.exec(f);if(!m||m[1].length<3)return;const k=m[1].toUpperCase(),s=m[2].toUpperCase();(pb.get(k)||pb.set(k,{}).get(k))[s]=i}));
pb.forEach(o=>{if(o.P!=null&&o.N!=null&&o.P!==o.N){PAIR.set(o.P,o.N);PAIR.set(o.N,o.P)}});
const S={view:stGet('view')==='t'?'t':'b',col:stGet('col')==='bank'?'bank':'role',dief:stGet('dief')==='f',f:+stGet('size')||58,
 roleOn:ROLE.map(()=>1),bankOn:Object.fromEntries(BK.map(b=>[b,1])),siteOn:[1,1,1],q:'',match:null,sel:null,hov:null,fit:false};
const svg=$('pk');svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
const el=(t,a,p)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);(p||svg).appendChild(e);return e};
const gOut=el('g',{}),gLab=el('g',{}),gBall=el('g',{}),gLink=el('line',{stroke:'var(--accent)','stroke-width':2.5,'stroke-linecap':'round'});gLink.style.display='none';
const outline=el('rect',{x:L-8,y:L-8,width:N*PK+16,height:R*PK+16,rx:8,fill:'none',stroke:'var(--line)','stroke-width':2},gOut);
const a1mark=el('path',{fill:'var(--accent)'},gOut);
const labs=[];for(let c=0;c<N;c++){for(const y of[L-12,H-L+19]){labs.push([el('text',{'text-anchor':'middle',y},gLab),c])}}
D.rows.forEach((r,j)=>{for(const x of[L-14,W-L+14]){el('text',{'text-anchor':'middle',x,y:L+(j+.5)*PK+3},gLab).textContent=r}});
const balls=[];
for(let j=0;j<R;j++)for(let c=0;c<N;c++){const i=at.get(j*100+c);const e=el('circle',{r:PK*.4},gBall);
 if(i==null){e.setAttribute('fill','none');e.setAttribute('stroke','var(--mut)');e.setAttribute('stroke-dasharray','2 2');e.setAttribute('opacity','.6');e.dataset.e=D.rows[j]+(c+1)}
 else e.dataset.i=i;balls.push([e,j,c,i])}
const dots=PR.map(()=>null);
balls.forEach(([e,j,c,i])=>{if(i!=null&&PR[i][4]!=null){dots[i]=el('circle',{r:2,fill:'var(--bg)','pointer-events':'none'},gBall)}});
const xOf=c=>L+((S.view==='b'?c:N-1-c)+.5)*PK,yOf=j=>L+(j+.5)*PK;
const ringG=el('g',{'pointer-events':'none'});
function focus(){return S.hov!=null?S.hov:S.sel}
function nmatch(i){return S.match===null||S.match.has(i)}
function render(){
 const f=focus(),fp=f!=null?PR[f]:null,pr=f!=null?PAIR.get(f):null;
 balls.forEach(([e,j,c,i])=>{const cx=xOf(c),cy=yOf(j);e.setAttribute('cx',cx);e.setAttribute('cy',cy);
  if(i==null)return;const p=PR[i];const col=S.col==='role'?css('--pn'+p[11]):bcol(p[2]);
  const on=S.roleOn[p[11]]&&S.bankOn[p[2]]&&S.siteOn[siteOf(p)];
  e.setAttribute('opacity',!on?.08:nmatch(i)?1:.22);
  if(p[12]){e.setAttribute('fill',col);e.setAttribute('stroke','none')}else{e.setAttribute('fill','none');e.setAttribute('stroke',col);e.setAttribute('stroke-width',2)}
  if(dots[i]){dots[i].setAttribute('cx',cx);dots[i].setAttribute('cy',cy);dots[i].setAttribute('opacity',!on?0:nmatch(i)?1:.22)}});
 ringG.remove();svg.appendChild(ringG);ringG.textContent='';
 const pos=i=>{const m=/^([A-Z]+)(\d+)$/.exec(PR[i][0]);return[xOf(+m[2]-1),yOf(D.rows.indexOf(m[1]))]};
 if(fp&&$('oBank').checked&&fp[2]!==''){PR.forEach((p,i)=>{if(p[2]===fp[2]&&i!==f){const[x,y]=pos(i);el('circle',{cx:x,cy:y,r:PK*.47,fill:'none',stroke:'var(--accent)','stroke-width':1.2,opacity:.8},ringG)}})}
 gLink.style.display='none';
 if(pr!=null&&$('oPair').checked){const[x1,y1]=pos(f),[x2,y2]=pos(pr);gLink.setAttribute('x1',x1);gLink.setAttribute('y1',y1);gLink.setAttribute('x2',x2);gLink.setAttribute('y2',y2);gLink.style.display='';
  svg.insertBefore(gLink,ringG);const[x,y]=[x2,y2];el('circle',{cx:x,cy:y,r:PK*.5,fill:'none',stroke:'var(--accent)','stroke-width':2.5},ringG)}
 S.match&&S.match.forEach(i=>{const[x,y]=pos(i);el('circle',{cx:x,cy:y,r:PK*.5,fill:'none',stroke:'var(--fg)','stroke-width':1.5},ringG)});
 if(f!=null){const[x,y]=pos(f);el('circle',{cx:x,cy:y,r:PK*.55,fill:'none',stroke:'var(--accent)','stroke-width':3},ringG)}
 labs.forEach(([t,c])=>{t.setAttribute('x',xOf(c));t.textContent=c+1});
 const bt=S.view==='b',cx=bt?L-8:W-L+8;
 a1mark.setAttribute('d',`M${cx} ${L-8} L${cx+(bt?1:-1)*20} ${L-8} L${cx} ${L+12} Z`);
 $('vlabel').textContent=bt?'Bottom view - ball side':'Top view - mirrored';
 $('vhint').textContent=bt?'Standard BGA pinout view: A1 top-left, as seen from the PCB side.':'Lid side, A1 top-right. Top = Bottom mirrored left-right, not rotated.';
 die(fp);cardRender()}
function cardRender(){const f=focus(),e=$('card');if(f==null){e.innerHTML='<span class="note">Hover or click a ball.</span>';return}e.innerHTML=cardHtml(f)+(S.hov!=null&&S.sel!=null&&S.hov!==S.sel?'':'')}
function cardHtml(i){const p=PR[i],src=D.src[p[14]],c=p[11]===undefined?'':css('--pn'+p[11]);
 const site=p[4]!=null?`${esc(p[7])} (tile X${p[4]} Y${p[5]}, z${p[6]})`:(p[16]?'none yet':'none expected (supply / NC)');
 let h=`<b style="font-size:16px">${esc(p[0])}</b> <span class="dot" style="background:${p[12]?c:'transparent'};border-color:${c}"></span> ${ROLE[p[11]]}${p[12]?'':' (not bonded)'}<table>`+
 `<tr><td>Pad number</td><td>${p[1]==null?'-':p[1]}</td></tr><tr><td>Bank / side</td><td>${esc(p[2]||'-')} / ${esc(p[3]||'-')}</td></tr><tr><td>Die site</td><td>${site}</td></tr>`+
 `<tr><td>I/O type</td><td>${esc(p[8]||'-')}</td></tr><tr><td>Vendor names</td><td>${p[9].length?p[9].map(esc).join(', '):'-'}</td></tr><tr><td>IBIS net</td><td>${esc(p[10]||'-')}</td></tr>`+
 `<tr><td>Special</td><td>${SP[p[11]]}</td></tr><tr><td>Usage default</td><td>${esc(p[13]||'-')}</td></tr>`+
 (PAIR.has(i)?`<tr><td>Pair partner</td><td><a href="#" data-go="${PAIR.get(i)}">${esc(PR[PAIR.get(i)][0])}</a></td></tr>`:'')+`</table>`+
 `<details><summary class="note">source fields</summary><table>${Object.keys(src).map(k=>`<tr><td>${esc(k)}</td><td>${src[k].map(esc).join(', ')}</td></tr>`).join('')}</table></details>`;
 for(const x of p[15])h+=`<div class="bad">conflict in ${esc(x.field)}: ${Object.keys(x.values).map(s=>esc(s)+' = '+esc(JSON.stringify(x.values[s]))).join('; ')}</div>`;
 return h}
$('card').addEventListener('click',e=>{const a=e.target.closest('[data-go]');if(a){e.preventDefault();S.sel=+a.dataset.go;S.hov=null;render()}});
// ---- die inset
function die(p){const g=$('die'),NXd=D.nx,NYd=D.ny,w=180,h=Math.round(w*NYd/NXd),ox=10,oy=10,fl=S.dief;g.setAttribute('viewBox',`0 0 200 ${h+30}`);
 const X=x=>ox+(fl?NXd-1-x:x)*w/NXd+w/NXd/2,Y=y=>oy+(NYd-1-y)*h/NYd+h/NYd/2;let s=`<rect x="${ox}" y="${oy}" width="${w}" height="${h}" fill="none" stroke="var(--mut)" stroke-width="1.5"/><rect x="${ox+w*.08}" y="${oy+h*.1}" width="${w*.84}" height="${h*.8}" fill="none" stroke="var(--line)"/>`;
 const edge=(sd)=>{const m={top:[ox,oy,ox+w,oy],bottom:[ox,oy+h,ox+w,oy+h],left:[fl?ox+w:ox,oy,fl?ox+w:ox,oy+h],right:[fl?ox:ox+w,oy,fl?ox:ox+w,oy+h]}[sd];return m?`<line x1="${m[0]}" y1="${m[1]}" x2="${m[2]}" y2="${m[3]}" stroke="var(--accent)" stroke-width="5" stroke-linecap="round"/>`:''};
 let note='Select a ball to see where it sits on the die.';
 if(p){if(p[4]!=null){s+=`<circle cx="${X(p[4])}" cy="${Y(p[5])}" r="5" fill="var(--accent)" stroke="var(--bg)" stroke-width="1.5"/>`;note=`${PR.indexOf(p)>=0?p[0]:''}: tile X${p[4]} Y${p[5]}, ${p[7]}.`}
  else if(p[16]){s+=edge(p[3]);note=`${p[0]}: no die site yet; `+(p[3]?`${p[3]} edge, bank ${p[2]||'-'}.`:'no side known.')}
  else note=`${p[0]}: supply / NC ball, no die site expected.`}
 s+=`<text x="${ox+w/2}" y="${h+oy+16}" text-anchor="middle">${fl?'seen from bottom (mirrored)':'seen from top surface'}</text>`;g.innerHTML=s;$('dnote').textContent=note}
// ---- controls
function sizePx(){const card=svg.parentElement.parentElement,w=card.clientWidth-26,top=card.getBoundingClientRect().top,h=Math.max(360,innerHeight-Math.max(top,0)-70);return Math.min(w,h*W/H)}
function size(){svg.style.width=Math.round(sizePx()*S.f/100)+'px';$('zoom').value=S.f;$('zv').textContent=S.f+' %'}
$('zoom').oninput=e=>{S.f=+e.target.value;stSet('size',S.f);size()};
$('fitbtn').onclick=()=>{S.f=100;stSet('size',100);size()};
addEventListener('resize',size);
document.querySelectorAll('input[name=view]').forEach(i=>{i.checked=i.value===S.view;i.onchange=()=>{S.view=i.value;stSet('view',S.view);render()}});
document.querySelectorAll('input[name=col]').forEach(i=>{i.checked=i.value===S.col;i.onchange=()=>{S.col=i.value;stSet('color',S.col);render()}});
document.querySelectorAll('input[name=dv]').forEach(i=>{i.checked=(i.value==='f')===S.dief;i.onchange=()=>{S.dief=i.value==='f';stSet('dief',S.dief?'f':'t');render()}});
['oBank','oPair'].forEach(id=>$(id).onchange=render);
function group(id,items,on){$(id).innerHTML=items.map(([name,n,sw,key],k)=>`<label class="lg"><input type="checkbox" data-k="${key!==undefined?key:k}" checked><span class="dot" style="${sw}"></span>${esc(name)}<span class="n">${n}</span></label>`).join('');
 $(id).querySelectorAll('input').forEach(c=>c.onchange=()=>{on(c.dataset.k,c.checked?1:0);render()})}
const rc=ROLE.map(()=>0);PR.forEach(p=>rc[p[11]]++);
const sw=(c)=>`background:${c};border-color:${c}`;
group('froles',ROLE.map((r,k)=>[r,rc[k],sw(`var(--pn${k})`),k]).filter(x=>x[1]),(k,v)=>S.roleOn[+k]=v);
group('fbanks',BK.map(b=>[b===''?'no bank':'Bank '+b,PR.filter(p=>p[2]===b).length,sw(bcol(b)),b]),(k,v)=>S.bankOn[k]=v);
const sc=[0,0,0];PR.forEach(p=>sc[siteOf(p)]++);
group('fsite',SITE.map((s,k)=>[s,sc[k],'border-color:var(--mut)']),(k,v)=>S.siteOn[+k]=v);
$('cnt').innerHTML=`<b>${PR.length}</b> balls in table of ${N*R} matrix positions (${N*R-PR.length} with no pin in table): <b>${sc[0]}</b> with die site, <b>${sc[1]}</b> no site yet, <b>${sc[2]}</b> no site expected. ${PAIR.size/2} differential pairs found in vendor names.`;
$('notes').innerHTML=D.notes.map(esc).join('<br>');
// ---- pointer, tap, search
const tip=$('tip');
function tgt(e){const t=e.target;return t.dataset&&t.dataset.i!=null?+t.dataset.i:null}
svg.addEventListener('mousemove',e=>{const i=tgt(e),t=e.target;
 if(i!==S.hov){S.hov=i;render()}
 if(i!=null){const p=PR[i];tip.textContent=`${p[0]}  ${p[9][0]||ROLE[p[11]]}  bank ${p[2]||'-'}`;tip.style.display='block'}
 else if(t.dataset&&t.dataset.e){tip.textContent=t.dataset.e+': no pin in table';tip.style.display='block'}else tip.style.display='none';
 tip.style.left=Math.min(e.clientX+14,innerWidth-200)+'px';tip.style.top=(e.clientY+14)+'px'});
svg.addEventListener('mouseleave',()=>{S.hov=null;tip.style.display='none';render()});
svg.addEventListener('click',e=>{const i=tgt(e);S.sel=i;render()});
function norm(s){return s.toLowerCase()}
function search(){const q=norm($('q').value.trim());S.q=q;
 if(!q){S.match=null;$('res').hidden=true;$('qn').textContent='';render();return}
 const ex=[],part=[];PR.forEach((p,i)=>{if(norm(p[0])===q)ex.push(i);else if(norm(p[0]).startsWith(q)||p[9].some(f=>norm(f).includes(q))||norm(p[10]).includes(q)||norm(p[7]).includes(q))part.push(i)});
 const m=ex.concat(part);S.match=new Set(m);$('res').hidden=false;
 $('res').innerHTML=m.slice(0,60).map(i=>`<div class="row" data-i="${i}"><b>${esc(PR[i][0])}</b><span class="m">${esc(PR[i][2]||'-')} / ${esc(PR[i][9].join(', ')||ROLE[PR[i][11]])}</span></div>`).join('')||'<div class="row"><span class="m">no match</span></div>';
 $('res').querySelectorAll('.row[data-i]').forEach(r=>r.onclick=()=>{S.sel=+r.dataset.i;render()});
 $('qn').textContent=`${m.length} match${m.length==1?'':'es'}, ringed on the map`+(m.length>60?' (first 60 listed)':'');render()}
$('q').oninput=search;$('q').onkeydown=e=>{if(e.key==='Enter'&&S.match&&S.match.size){S.sel=[...S.match][0];render()}};
// ---- panels
function dk(k){return 'pnl:'+k}
document.querySelectorAll('details.pnl').forEach(d=>{const v=stGet(dk(d.id));if(v!==null)d.open=v==='1';d.addEventListener('toggle',()=>stSet(dk(d.id),d.open?'1':'0'))});
$('pexp').onclick=()=>document.querySelectorAll('details.pnl').forEach(d=>d.open=true);
$('pcol').onclick=()=>document.querySelectorAll('details.pnl').forEach(d=>d.open=false);
$('h1').textContent=D.title;
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',render);
size();render();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", help="SQLite file (default: PLURIBUS_SQLITE_PATH or databases/cycloneiv/gx150.db)")
    ap.add_argument("--device", default="EP4CGX150")
    ap.add_argument("--package", default="DF31")
    ap.add_argument("--out", default=str(GEO / "package_map.html"))
    a = ap.parse_args()
    if a.db:
        os.environ["PLURIBUS_SQLITE_PATH"] = a.db
    dev = a.device + a.package
    pins = geo_pins.load_pins(dev)
    rows = pins["p"]
    balls = {}
    for r in rows:
        m = re.fullmatch(r"([A-Z]+)(\d+)", r[0])
        if not m:
            raise SystemExit(f"geo_package: ball name {r[0]!r} is not letters+digits")
        balls[r[0]] = (m.group(1), int(m.group(2)))
    letters = sorted({b[0] for b in balls.values()}, key=lambda s: (len(s), s))
    ncol = max(b[1] for b in balls.values())
    singles = [c for c in string.ascii_uppercase if c not in letters]
    seq = [c for c in string.ascii_uppercase if c in letters]
    dbl = sorted(l[1] for l in letters if len(l) == 2)
    dbl_missing = [c for c in string.ascii_uppercase[: string.ascii_uppercase.index(dbl[-1]) + 1] if c not in dbl]
    absent = [f"{l}{c}" for l in letters for c in range(1, ncol + 1) if f"{l}{c}" not in balls]
    nx = ny = None
    tj = GEO / "tiles.json"
    if tj.exists():
        d = json.load(open(tj))
        nx, ny = d["xmax"] + 1, d["ymax"] + 1
    if nx is None:
        nx = max(r[4] for r in rows if r[4] is not None) + 1
        ny = max(r[5] for r in rows if r[5] is not None) + 1
    notes = [
        f"{len(rows)} balls in the table; matrix {len(letters)} rows x {ncol} columns = {len(letters) * ncol} positions.",
        "Row letters present: " + " ".join(letters) + ". Omitted: " + " ".join(singles) + " and " + ", ".join("A" + c for c in dbl_missing) + " (letters FBGA drawings skip because they read as digits).",
        "Positions with no pin in the table: " + (", ".join(absent) or "none") + ".",
        "Bottom view = ball side as seen from the PCB (A1 top-left). Top view = the same grid mirrored left-right, not rotated.",
        "Differential pairs come from vendor names ending p/n after a digit or underscore with a matching partner (e.g. DIFFIO_B1p / DIFFIO_B1n).",
        "Roles: power, ground and NC balls have no die site expected; all others should have one. Grey ring on the map marks selection, dim = filtered out.",
    ]
    data = dict(pins, rows=letters, cols=ncol, nx=nx, ny=ny, notes=notes, title=f"{a.device} {a.package} package ball map ({len(rows)} balls)")
    page = geo_pins.inject(PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":"), ensure_ascii=False)), pins)
    # counts in the page must equal an independent DB query
    con = sqlite3.connect(f"file:{os.environ.get('PLURIBUS_SQLITE_PATH') or REPO / 'databases/cycloneiv/gx150.db'}?mode=ro", uri=True)
    tot, site = con.execute("select count(*), sum(tile_x is not null) from device_pins where device=?", (dev,)).fetchone()
    con.close()
    exp = sum(1 for r in rows if r[4] is None and not r[16])
    assert tot == len(rows) and site == sum(r[4] is not None for r in rows), "page counts differ from DB"
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(page)
    print(f"wrote {a.out}: {tot} balls, {site} with site, {tot - site - exp} no site yet, {exp} no site expected, "
          f"{len(letters)}x{ncol} grid, absent {absent}, omitted {singles}+{dbl_missing}, {len(page) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
