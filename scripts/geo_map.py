#!/usr/bin/env python3.15t
"""Die map: tmp/geo/tiles.json -> tmp/geo/die.geojson + tmp/geo/die_map.html (self-contained, no network).

  python3.15t scripts/geo_map.py
Derived display data only (docs/geo-investigation.md).  The page carries no file paths.
Pin layer on the IO ring: scripts/geo_pins.py, docs/geo-pins.md.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEO = REPO / "tmp/geo"
sys.path.insert(0, str(REPO / "scripts"))
import geo_pins  # noqa: E402  (pin layer: device_pins -> page)

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Die coverage map</title>
<style>
:root{--bg:#fbfbfa;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#d9d8d3;--ver:#2f9e6a;--evi:#e0a31b;--unk:#b9b8b2;--lab:#4f7fd0;--m9k:#9b59b6;--mul:#d9693a;--io:#3aa7a7;--accent:#2a5bd7}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#17181a;--fg:#e8e8e4;--mut:#9a9a94;--card:#202225;--line:#38393c;--ver:#46c08a;--evi:#f0b93a;--unk:#55565a;--lab:#6c9bf0;--m9k:#c08be0;--mul:#f08a5a;--io:#55c4c4;--accent:#7fa2ff}}
:root[data-theme=dark]{--bg:#17181a;--fg:#e8e8e4;--mut:#9a9a94;--card:#202225;--line:#38393c;--ver:#46c08a;--evi:#f0b93a;--unk:#55565a;--lab:#6c9bf0;--m9k:#c08be0;--mul:#f08a5a;--io:#55c4c4;--accent:#7fa2ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;padding:16px}
h1{font-size:20px;margin:0 0 2px}p.sub{margin:0 0 12px;color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
canvas{width:100%;height:auto;display:block;border-radius:6px;cursor:crosshair}
fieldset{border:0;padding:0;margin:0 0 12px}legend{font-weight:600;margin-bottom:4px}
label{display:flex;gap:6px;align-items:center;margin:2px 0;cursor:pointer}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
#info{min-height:132px;font-variant-numeric:tabular-nums}#info b{font-weight:600}
table{border-collapse:collapse;width:100%;font-size:13px}td{padding:1px 0}td:last-child{text-align:right}
.note{color:var(--mut);font-size:12px;margin-top:8px}
.scroll{overflow:auto;max-height:78vh}
/*__PINS_CSS__*/
</style></head><body>
<h1>EP4CGX150 die map</h1>
<p class="sub">Each cell is one tile (x across, y up). Colour = configuration-bit evidence for the tile. Hover for details.</p>
<div class="wrap">
<div><div class="card" style="overflow:auto"><canvas id="c" role="img" aria-label="Die tile map coloured by evidence tier"></canvas></div></div>
<aside id="side">
<!--__PANEL_BAR__-->
<details class="pnl" id="pn-ctl" open><summary>Colour, layers and size</summary><div class="pb">
<fieldset><legend>Colour by</legend>
<label><input type="radio" name="mode" value="tier" checked> Evidence tier</label>
<label><input type="radio" name="mode" value="dens"> Image set-bit density</label>
<label><input type="radio" name="mode" value="kind"> Tile kind</label></fieldset>
<fieldset><legend>Show tiles</legend>
<label><input type="checkbox" data-k="LAB" checked><span class="sw" style="background:var(--lab)"></span>LAB</label>
<label><input type="checkbox" data-k="M9K" checked><span class="sw" style="background:var(--m9k)"></span>M9K memory</label>
<label><input type="checkbox" data-k="MUL" checked><span class="sw" style="background:var(--mul)"></span>Multiplier</label>
<label><input type="checkbox" data-k="IO" checked><span class="sw" style="background:var(--io)"></span>IO (ring)</label></fieldset>
<fieldset><legend>Overlays</legend>
<label><input type="checkbox" id="oEdge"> Die-edge tiles</label>
<label><input type="checkbox" id="oSpec" checked> Specimen LABs (ring)</label>
<label><input type="checkbox" id="oLe" checked> LE-output grids (dot)</label>
</fieldset>
<!--__SIZE_HTML__-->
<div id="legend"></div></div></details>
<details class="pnl" id="pn-info" open><summary>Hovered tile</summary><div class="pb"><div id="info">Hover a tile.</div></div></details>
<!--__PINS_HTML__-->
<details class="pnl" id="pn-notes"><summary>Notes</summary><div class="pb"><p class="note" style="margin:0">Tier: verified = LUT INIT bits checked against a vendor netlist (256 of a LAB tile's cells). Evidence = a LAB with measured routing specimens. Unknown = no bit attributed. Density = set bits of one example design binned to tiles; the row binning is approximate.</p></div></details>
</aside></div>
<script>
const D=__DATA__;
const NX=D.nx,NY=D.ny,T=D.t; // t rows: [x,y,kind,tier,cells,ver,set,edge,spec,leout]
const KIND=["LAB","M9K","MUL","IO"],TIER=["verified","evidence","unknown"];
const cv=document.getElementById('c'),ctx=cv.getContext('2d'),M=2;let S=10;
const grid=new Map();T.forEach(t=>grid.set(t[0]*1000+t[1],t));
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const kv=k=>k=="IOL"||k=="IOR"||k=="IOROW"?"IO":k;
let mode="tier",hover=null;const vis={LAB:1,M9K:1,MUL:1,IO:1};
const maxSet=Math.max(...T.map(t=>t[6]));
function dens(v){const f=Math.sqrt(v/maxSet);const a=[247,247,240],b=[34,70,160];return `rgb(${a.map((x,i)=>Math.round(x+(b[i]-x)*f)).join(',')})`}
function colour(t){const k=kv(t[2]);if(mode=="tier")return css('--'+{verified:'ver',evidence:'evi',unknown:'unk'}[t[3]]);
 if(mode=="kind")return css('--'+{LAB:'lab',M9K:'m9k',MUL:'mul',IO:'io'}[k]);return dens(t[6])}
function draw(){size();const w=cv.width,h=cv.height;ctx.clearRect(0,0,w,h);ctx.fillStyle=css('--card');ctx.fillRect(0,0,w,h);
 for(const t of T){const k=kv(t[2]);const px=M+t[0]*S,py=M+(NY-1-t[1])*S;
  if(!vis[k]){ctx.fillStyle=css('--line');ctx.globalAlpha=.35;ctx.fillRect(px,py,S-1,S-1);ctx.globalAlpha=1;continue}
  ctx.fillStyle=colour(t);ctx.fillRect(px,py,S-1,S-1);
  if(document.getElementById('oEdge').checked&&t[7]){ctx.strokeStyle=css('--fg');ctx.lineWidth=1;ctx.strokeRect(px+.5,py+.5,S-2,S-2)}
  if(document.getElementById('oSpec').checked&&t[8]){ctx.strokeStyle=css('--accent');ctx.lineWidth=2;ctx.strokeRect(px-1,py-1,S+1,S+1)}
  if(document.getElementById('oLe').checked&&t[9]){ctx.fillStyle=css('--fg');ctx.beginPath();ctx.arc(px+S/2-.5,py+S/2-.5,2,0,7);ctx.fill()}}
 if(hover){const px=M+hover[0]*S,py=M+(NY-1-hover[1])*S;ctx.strokeStyle=css('--fg');ctx.lineWidth=2;ctx.strokeRect(px-1,py-1,S+1,S+1)}
  pinsDraw();legend()}
function legend(){const L=document.getElementById('legend');let h="";
 if(mode=="tier")h=TIER.map(x=>`<label style="cursor:default"><span class="sw" style="background:${css('--'+{verified:'ver',evidence:'evi',unknown:'unk'}[x])}"></span>${x}</label>`).join("");
 else if(mode=="kind")h=KIND.map(x=>`<label style="cursor:default"><span class="sw" style="background:${css('--'+{LAB:'lab',M9K:'m9k',MUL:'mul',IO:'io'}[x])}"></span>${x}</label>`).join("");
 else h=`<div style="height:10px;border-radius:3px;background:linear-gradient(90deg,${dens(0)},${dens(maxSet)})"></div><div class="note" style="margin:2px 0 0;display:flex;justify-content:space-between"><span>0</span><span>${maxSet} set bits</span></div>`;
 L.innerHTML=h}
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect(),sx=cv.width/r.width;const x=Math.floor(((e.clientX-r.left)*sx-M)/S),y=NY-1-Math.floor(((e.clientY-r.top)*sx-M)/S);
 const t=grid.get(x*1000+y);hover=t||null;draw();const I=document.getElementById('info');
 if(!t){I.textContent="Hover a tile.";return}
 I.innerHTML=`<b>X${t[0]} Y${t[1]}</b> &nbsp;${t[2]}<table><tr><td>Evidence tier</td><td>${t[3]}</td></tr><tr><td>Cells in tile band</td><td>${t[4].toLocaleString()}</td></tr><tr><td>Verified cells</td><td>${t[5]} (${(100*t[5]/t[4]).toFixed(1)}%)</td></tr><tr><td>Example image set bits</td><td>${t[6]}</td></tr><tr><td>Die-edge tile</td><td>${t[7]?'yes':'no'}</td></tr><tr><td>Specimen LAB</td><td>${t[8]?'yes':'no'}</td></tr><tr><td>LE-output grid</td><td>${t[9]?'yes':'no'}</td></tr></table>`});
cv.addEventListener('mouseleave',()=>{hover=null;draw()});
document.querySelectorAll('input[name=mode]').forEach(i=>i.onchange=()=>{mode=i.value;draw()});
document.querySelectorAll('[data-k]').forEach(i=>i.onchange=()=>{vis[i.dataset.k]=i.checked?1:0;draw()});
['oEdge','oSpec','oLe'].forEach(id=>document.getElementById(id).onchange=draw);

/*__PINS_JS__*/
matchMedia('(prefers-color-scheme:dark)').addEventListener('change',draw);draw();
</script></body></html>
"""


def main():
    d = json.load(open(GEO / "tiles.json"))
    kmap = {"LAB": "LAB", "M9K": "M9K", "MUL": "MUL", "IOL": "IOL", "IOR": "IOR", "IOROW": "IOROW"}
    rows = [[t["x"], t["y"], kmap[t["kind"]], t["tier"], t["cells"], t["ver"], t["set"], t["edge"], t["spec"], t["leout"]]
            for t in d["tiles"]]
    data = {"nx": d["xmax"] + 1, "ny": d["ymax"] + 1, "t": rows}
    pins = geo_pins.load_pins()
    page = geo_pins.inject(PAGE.replace("__DATA__", json.dumps(data, separators=(",", ":"))), pins)
    (GEO / "die_map.html").write_text(page)
    feats = [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[t["x"], t["y"]], [t["x"] + 1, t["y"]], [t["x"] + 1, t["y"] + 1], [t["x"], t["y"] + 1], [t["x"], t["y"]]]]},
              "properties": {k: t[k] for k in ("x", "y", "kind", "tier", "cells", "ver", "set", "edge")}} for t in d["tiles"]]
    (GEO / "die.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    print("wrote", GEO / "die_map.html", len(rows), "tiles,", len(pins["p"]), "pins,", f"{len(page) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
