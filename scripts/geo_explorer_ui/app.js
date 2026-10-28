'use strict';
const G=__DATA__;
// ======================= core: data access, store, state =======================
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const Store={get(k){try{return localStorage.getItem('geo-x:'+k)}catch(e){return null}},set(k,v){try{localStorage.setItem('geo-x:'+k,v)}catch(e){}}};
const T=G.tiles,NX=T.nx,NY=T.ny,NT=NX*NY,P=G.pins,PR=P.rows,SP=P.roles,IM=G.image,GR=G.grid,VP=G.geom.vpitch||0,VLO=G.geom.vband_lo||0;
const PK0=G.package,PERI=PK0.layout==='perimeter',UIH=G.ui,PAT=G.pattern,GEO=P.geo,BRD=P.board||null,DSG=G.design||null;
const F=Object.fromEntries(P.cols.map((c,i)=>[c,i]));          // pin row field index by name
const TP=G.xref.tile_pins;                                      // tile index -> [pin index]
const tx=i=>Math.floor(i/NY),ty=i=>i%NY;
const KIND=T.kinds,KG=UIH.kind_groups,TG=Array.from({length:NT},(_,i)=>KG[UIH.kind_group[T.kind[i]]].id);
const KCOL=Object.fromEntries(KG.map(g=>[g.id,'--k'+g.slot])),TIERC=UIH.tier_class.map(c=>({ver:'--ver',evi:'--evi',unk:'--unk'}[c]));
const ROLE=UIH.role_labels,SITE=UIH.site_labels;
const siteOf=p=>p[F.tile]>=0?0:(p[F.expected]?1:2);
const BK=[...new Set(PR.map(p=>p[F.bank]))].sort((a,b)=>(a===''?1:0)-(b===''?1:0)||a.localeCompare(b,undefined,{numeric:true}));
const PTL=Object.keys(TP).map(k=>[+k,TP[k]]);
const NCOL=PERI?0:GR.cols,NROW=PERI?0:GR.letters.length;
const PVARS=['--bg','--fg','--mut','--card','--line','--ver','--evi','--unk','--ovh','--bad','--lab','--m9k','--mul','--io','--accent','--bkl'].concat(KG.map(g=>'--k'+g.slot),SP.map((_,i)=>'--pn'+i));
const PAL={};function readPal(){const cs=getComputedStyle(document.documentElement);PVARS.forEach(v=>PAL[v]=cs.getPropertyValue(v).trim())}
const css=n=>PAL[n];
const chk=id=>$(id).checked;
const rad=n=>{const e=document.querySelector(`input[name=${n}]:checked`);return e?e.value:null};
const VIEW=()=>PERI?'b':rad('view');                              // perimeter packages have the top view only
const FLIP=()=>!PERI&&rad('dv')==='f';
const imgOn=()=>!!IM&&chk('oImg');
const boardName=i=>{const b=BRD&&BRD[i];return b?(b.name||b.sig||b.net||''):''};
const lbl=i=>{const p=PR[i],m=rad('lab')||'num';return m==='vendor'?(p[F.names][0]||p[F.ball]):m==='board'?(boardName(i)||p[F.ball]):p[F.ball]};
// persisted inputs: checkbox by id, radio by name
function persist(el){
 if(el.type==='range'){const k='v:'+el.id,v=Store.get(k);if(v!==null)el.value=v;el.addEventListener('input',()=>Store.set(k,el.value));return}
 if(el.type==='checkbox'){const k='c:'+el.id,v=Store.get(k);if(v!==null)el.checked=v==='1';el.addEventListener('change',()=>Store.set(k,el.checked?'1':'0'))}
 else if(el.type==='radio'){const k='r:'+el.name,v=Store.get(k);if(v!==null)el.checked=el.value===v;el.addEventListener('change',()=>{if(el.checked)Store.set(k,el.value)})}}
const ST={tab:'die',sel:{tile:-1,pin:-1},hov:{tile:-1,pin:-1},match:null,roleOn:SP.map(()=>1),bankOn:Object.fromEntries(BK.map(b=>[b,1])),siteOn:[1,1,1]};
const VIS=Object.fromEntries(KG.map(g=>[g.id,1])),IOG=KG.filter(g=>UIH.io_groups.includes(g.slot)).map(g=>g.id);
const pinOn=i=>{const p=PR[i];return ST.roleOn[p[F.role]]&&ST.bankOn[p[F.bank]]&&ST.siteOn[siteOf(p)]};
const pcol=i=>css('--pn'+PR[i][F.role]);
const BKC=b=>b===''?css('--mut'):`hsl(${Math.round(360*BK.indexOf(b)/BK.length)} 65% ${css('--bkl')})`;

// ======================= selection (shared by all views) =======================
function selectPin(i){ST.sel={pin:i,tile:i>=0?PR[i][F.tile]:-1}}
function selectTile(t){ST.sel={tile:t,pin:-1}}
function focusPin(){return ST.hov.pin>=0?ST.hov.pin:ST.sel.pin}
function matchSet(){return ST.match||new Set()}
let raf=0;function render(){if(!raf)raf=requestAnimationFrame(()=>{raf=0;renderNow()})}
function renderNow(){readPal();applyVis();if(ST.tab==='pkg')PkgView.draw();else if(ST.tab==='chip')ChipView.draw();else TileView.draw();Panels.update()}
function applyVis(){document.querySelectorAll('[data-tabs],[data-needs],[data-pk]').forEach(e=>{
 const t=e.dataset.tabs,n=e.dataset.needs,k=e.dataset.pk;e.hidden=(t&&!t.split(' ').includes(ST.tab))||(n==='img'&&!imgOn())||(k&&!k.split(' ').includes(PERI?'peri':'bga'))})}
function setTab(t){if(t==='known'&&!imgOn())t='die';ST.tab=t;ST.hov={tile:-1,pin:-1};Store.set('tab',t);
 document.querySelectorAll('.tabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===t?'true':'false'));
 Sizer.sync();renderNow()}
function goPin(i,zoom){ // select a pin and bring it into view in the active view
 selectPin(i);const t=PR[i][F.tile];
 if((ST.tab==='die'||ST.tab==='known')&&t>=0){IOG.forEach(g=>{VIS[g]=1;$('k'+g).checked=true});if(zoom!==false)Sizer.atLeast(40);renderNow();TileView.reveal(t)}
 else{renderNow();if(ST.tab==='pkg'||ST.tab==='chip'){const cd=$(ST.tab==='pkg'?'pkgcard':'chipcard'),b=cd.getBoundingClientRect();if(b.top<0||b.top>innerHeight)cd.scrollIntoView({block:'center'})}}}

// ======================= size: one slider + Fit for the active view =======================
const WIDE=()=>matchMedia('(min-width:1100px)').matches;
function availH(card,reserve){return WIDE()?card.clientHeight-26-(reserve||0):Math.max(360,innerHeight-Math.max(card.getBoundingClientRect().top,0)-(reserve||0)-28)}
const isPk=()=>ST.tab==='pkg'||ST.tab==='chip';
const Sizer={tiles:{fit:true,px:10},pkg:100,
 init(){const a=+Store.get('size-tiles');if(a>=4&&a<=56){this.tiles.fit=false;this.tiles.px=a}const b=+Store.get('size-pkg');if(b>=30&&b<=100)this.pkg=b;
  $('zoom').oninput=e=>this.set(+e.target.value);$('fitbtn').onclick=()=>this.set(isPk()?100:TileView.fitPx());addEventListener('resize',()=>render())},
 set(v){if(isPk()){this.pkg=Math.max(30,Math.min(100,v));Store.set('size-pkg',this.pkg)}else{this.tiles.fit=false;this.tiles.px=Math.max(4,Math.min(56,v));Store.set('size-tiles',this.tiles.px)}this.sync();renderNow()},
 atLeast(v){if(this.tiles.px<v||this.tiles.fit){this.tiles.fit=false;this.tiles.px=Math.max(this.tiles.px,v);Store.set('size-tiles',this.tiles.px)}},
 sync(){const z=$('zoom');if(isPk()){z.min=30;z.max=100;z.value=this.pkg;$('zv').textContent=this.pkg+' %'}else{z.min=4;z.max=56;z.value=this.tiles.px;$('zv').textContent=this.tiles.px+' px'}}};

// ======================= tile views (Die map + Known cells share one canvas) =======================
const TileView=(()=>{
 const cv=$('c'),ctx=cv.getContext('2d'),M=2;let TS=10;
 const maxSet=Math.max(1,...T.set),maxDens=IM?Math.max(...IM.cells.map((c,i)=>c?IM.set[i]/c:0)):1;
 const ramp=f=>{f=Math.max(0,Math.min(1,f));const a=[247,247,240],b=[34,70,160];return `rgb(${a.map((x,i)=>Math.round(x+(b[i]-x)*f)).join(',')})`};
 function fitPx(){const card=cv.parentElement,w=card.clientWidth-26,h=availH(card,0);return Math.max(4,Math.min(56,Math.floor(Math.min((w-2*M)/NX,(h-2*M)/NY))))}
 function resize(){if(Sizer.tiles.fit)Sizer.tiles.px=Math.max(4,fitPx());TS=Sizer.tiles.px;Sizer.sync();
  const w=NX*TS+2*M,h=NY*TS+2*M;if(cv.width!=w)cv.width=w;if(cv.height!=h)cv.height=h;cv.style.width=w+'px'}
 const pxy=i=>[M+tx(i)*TS,M+(NY-1-ty(i))*TS];
 function tileFill(i,px,py,known){
  const s=TS-1,g=TG[i];
  if(!known){const m=rad('dmode');ctx.fillStyle=m==='tier'?css(TIERC[T.tier[i]]):m==='kind'?css(KCOL[g]):ramp(Math.sqrt(T.set[i]/maxSet));ctx.fillRect(px,py,s,s);return}
  const m=rad('kmode');
  if(m==='share'){const a=IM.sv[i],b=IM.se[i],c=IM.su[i],tot=a+b+c;ctx.fillStyle=css('--line');ctx.globalAlpha=.4;ctx.fillRect(px,py,s,s);ctx.globalAlpha=1;
   if(tot>0){let y=py+s;for(const [n,col] of [[a,'--ver'],[b,'--evi'],[c,'--unk']]){const h=s*n/tot;ctx.fillStyle=css(col);ctx.fillRect(px,y-h,s,h);y-=h}}}
  else if(m==='dens'){ctx.fillStyle=ramp(Math.sqrt((IM.cells[i]?IM.set[i]/IM.cells[i]:0)/maxDens));ctx.fillRect(px,py,s,s)}
  else if(m==='cap'){ctx.fillStyle=ramp((IM.capv[i]+IM.cape[i])/Math.max(IM.cells[i],1));ctx.fillRect(px,py,s,s)}
  else{ctx.fillStyle=css(KCOL[g]);ctx.fillRect(px,py,s,s)}}
 function pinPos(n,k,lab){if(lab){const rh=TS/4,top=(TS-1-rh*n)/2;return [TS*.14,top+rh*(k+.5)]}
  const w=(TS-1)/2;if(n<=2)return [w*(k+.5),(TS-1)/2];return [w*((k&1)+.5),w*((k>>1)+.5)]}
 function pinsDraw(hiPins,hiTiles){
  if(!chk('oPins')||!IOG.some(g=>VIS[g]))return;
  const lab=TS>=32&&chk('oPinLab'),r=lab?Math.max(2,TS*.06):Math.max(1.4,TS*.16);ctx.textBaseline='middle';
  for(const [t,a0] of PTL){const a=a0.filter(pinOn);if(!a.length)continue;const [px,py]=pxy(t),n=a.length;
   a.forEach((i,k)=>{const [dx,dy]=pinPos(n,k,lab),cx=px+dx,cy=py+dy,c=pcol(i),p=PR[i];
    ctx.beginPath();ctx.arc(cx,cy,r,0,7);
    if(p[F.bonded]){ctx.fillStyle=c;ctx.fill()}else{ctx.strokeStyle=c;ctx.lineWidth=Math.max(1,r*.45);ctx.stroke()}
    if(hiPins.has(i)){ctx.beginPath();ctx.arc(cx,cy,r+3,0,7);ctx.strokeStyle=css('--accent');ctx.lineWidth=2;ctx.stroke()}
    if(lab){const f=Math.min(TS/4*.85,(TS-dx-r-3)/(.62*p[F.ball].length+.2));ctx.font=`${f}px system-ui,sans-serif`;ctx.fillStyle=css('--fg');ctx.fillText(p[F.ball],cx+r+2,cy)}});
   if(hiTiles.has(t)){ctx.strokeStyle=css('--accent');ctx.lineWidth=2;ctx.strokeRect(px-1,py-1,TS+1,TS+1)}}}
 function draw(){
  resize();const known=ST.tab==='known'&&imgOn(),w=cv.width,h=cv.height;
  ctx.clearRect(0,0,w,h);ctx.fillStyle=css('--card');ctx.fillRect(0,0,w,h);
  const z=known&&chk('oZero'),ed=!known&&chk('oEdge'),sp=!known&&chk('oSpec'),le=!known&&chk('oLe');
  for(let i=0;i<NT;i++){const [px,py]=pxy(i);
   if(!VIS[TG[i]]){ctx.fillStyle=css('--line');ctx.globalAlpha=known?.3:.35;ctx.fillRect(px,py,TS-1,TS-1);ctx.globalAlpha=1;continue}
   tileFill(i,px,py,known);const f=T.flag[i];
   if(known){if(z&&(IM.sv[i]+IM.se[i]+IM.su[i])>0&&(IM.sv[i]+IM.se[i])==0){ctx.strokeStyle=css('--bad');ctx.lineWidth=1.5;ctx.strokeRect(px+.5,py+.5,TS-2,TS-2)}}
   else{if(ed&&(f&1)){ctx.strokeStyle=css('--fg');ctx.lineWidth=1;ctx.strokeRect(px+.5,py+.5,TS-2,TS-2)}
    if(sp&&(f&2)){ctx.strokeStyle=css('--accent');ctx.lineWidth=2;ctx.strokeRect(px-1,py-1,TS+1,TS+1)}
    if(le&&(f&4)){ctx.fillStyle=css('--fg');ctx.beginPath();ctx.arc(px+TS/2-.5,py+TS/2-.5,2,0,7);ctx.fill()}}}
  for(const [t,c] of [[ST.sel.tile,'--accent'],[ST.hov.tile,'--fg']]){if(t<0||(c==='--accent'&&!chk('oSel')))continue;const [px,py]=pxy(t);ctx.strokeStyle=css(c);ctx.lineWidth=2;ctx.strokeRect(px-1,py-1,TS+1,TS+1)}
  const hiP=new Set(matchSet()),hiT=new Set();if(ST.sel.pin>=0)hiP.add(ST.sel.pin);
  hiP.forEach(i=>{const t=PR[i][F.tile];if(t>=0)hiT.add(t)});
  pinsDraw(hiP,hiT);legend(known)}
 function legend(known){const L=$('legend');let h='';
  if(!known){const m=rad('dmode');
   if(m==='tier')h=T.tiers.map((x,i)=>`<label style="cursor:default"><span class="sw" style="background:${css(TIERC[i])}"></span>${x}</label>`).join('');
   else if(m==='kind')h=Object.keys(KCOL).map(x=>`<label style="cursor:default"><span class="sw" style="background:${css(KCOL[x])}"></span>${x}</label>`).join('');
   else h=`<div style="height:10px;border-radius:3px;background:linear-gradient(90deg,${ramp(0)},${ramp(1)})"></div><div class="note" style="margin:2px 0 0;display:flex;justify-content:space-between"><span>0</span><span>${maxSet} set bits (sqrt scale)</span></div>`}
  else{const m=rad('kmode');
   if(m==='share')h=[['--ver','verified-class set bits'],['--evi','evidence-class'],['--unk','unknown-class']].map(([c,n])=>`<label style="cursor:default"><span class="sw" style="background:${css(c)}"></span>${n}</label>`).join('')+`<div class="note" style="margin:2px 0 0">Bar height = share of the tile's set bits (CRC bytes excluded).</div>`;
   else if(m==='kind')h=Object.keys(KCOL).map(x=>`<label style="cursor:default"><span class="sw" style="background:${css(KCOL[x])}"></span>${x}</label>`).join('');
   else h=`<div style="height:10px;border-radius:3px;background:linear-gradient(90deg,${ramp(0)},${ramp(1)})"></div><div class="note" style="margin:2px 0 0;display:flex;justify-content:space-between"><span>0</span><span>${m==='dens'?'set / cells (sqrt scale), max '+(100*maxDens).toFixed(1)+' %':'known cells / cells, 100 %'}</span></div>`}
  L.innerHTML=h}
 function tileAt(e){const r=cv.getBoundingClientRect(),sx=cv.width/r.width;const x=Math.floor(((e.clientX-r.left)*sx-M)/TS),y=NY-1-Math.floor(((e.clientY-r.top)*sx-M)/TS);return x>=0&&x<NX&&y>=0&&y<NY?x*NY+y:-1}
 function reveal(t){const sc=cv.parentElement,k=cv.getBoundingClientRect().width/cv.width;
  sc.scrollLeft=(M+tx(t)*TS+TS/2)*k-sc.clientWidth/2;sc.scrollTop=(M+(NY-1-ty(t))*TS+TS/2)*k-sc.clientHeight/2;
  const b=cv.getBoundingClientRect();if(b.top<0||b.top>innerHeight)cv.scrollIntoView({block:'center'})}
 cv.addEventListener('mousemove',e=>{const t=tileAt(e);if(t!==ST.hov.tile){ST.hov.tile=t;render()}});
 cv.addEventListener('mouseleave',()=>{ST.hov.tile=-1;render()});
 cv.addEventListener('click',e=>{selectTile(tileAt(e));render()});
 return {draw,reveal,fitPx,tileAt,ramp,maxSet,maxDens}})();

// ======================= image layer: decoded blobs, per-tile info, bitmap =======================
const Img=(()=>{
 let CT=null,SB=null,SOFF=null,bsel=-1,bkey='',bsc=1;const bm=$('bm'),bx=bm.getContext('2d');
 const CL=IM?IM.cls:[],TV={V:'--ver',E:'--evi',U:'--unk',O:'--ovh'},pc=(a,b)=>b?(100*a/b).toFixed(1)+' %':'-';
 async function inflate(b64){const bin=atob(b64),u=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)u[i]=bin.charCodeAt(i);
  return new Uint8Array(await new Response(new Blob([u]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer())}
 async function init(){if(!IM)return;try{CT=await inflate(IM.C);SB=await inflate(IM.S);SOFF=new Array(NT);let o=0;for(let i=0;i<NT;i++){SOFF[i]=o;o+=Math.ceil(IM.w[i]*VP/8)}}
  catch(e){CT=null;$('bmi').textContent='Bitmaps need DecompressionStream (a current browser).'}
  ['tint','onlyset','csz'].forEach(id=>$(id).oninput=()=>drawBm());render()}
 const bit=(soff,k)=>(SB[soff+(k>>3)]>>(7-(k&7)))&1;
 function breakdown(i){if(!CT)return'';const off=IM.tp[IM.tmpl[i]][0],so=SOFF[i],n=new Array(CL.length+1).fill(0),s=new Array(CL.length+1).fill(0);
  for(let c=0;c<IM.w[i];c++)for(let r=0;r<VP;r++){const k=c*VP+r,cl=CT[off+k];if(!cl)continue;n[cl]++;if(bit(so,k))s[cl]++}
  let h='<table class="num"><tr><th>class</th><th>cells</th><th>set</th></tr>';
  for(let q=1;q<=CL.length;q++)if(n[q])h+=`<tr><td><span class="sw" style="background:${css(TV[CL[q-1][1]])};margin-right:4px"></span>${CL[q-1][0]}</td><td>${n[q]}</td><td>${s[q]}</td></tr>`;
  return h+'</table>'}
 function dieHtml(i){const f=T.flag[i],FL=T.flags,fl=n=>FL.indexOf(n)>=0?(f>>FL.indexOf(n))&1:null,yn=v=>v?'yes':'no';
  let h=`<b>X${tx(i)} Y${ty(i)}</b> &nbsp;${KIND[T.kind[i]]}<table><tr><td>Evidence tier</td><td>${esc(T.tiers[T.tier[i]])}</td></tr><tr><td>Cells in tile${VP?' band':''}</td><td>${T.cells[i].toLocaleString()}</td></tr><tr><td>Verified cells</td><td>${T.ver[i]} (${(100*T.ver[i]/Math.max(1,T.cells[i])).toFixed(1)}%)</td></tr><tr><td>${esc(UIH.set_label)}</td><td>${T.set[i]}</td></tr>`;
  if(DSG)h+=Object.keys(DSG.cols).map(k=>`<tr><td>${esc(DSG.names[k])}</td><td>${DSG.cols[k][i]}</td></tr>`).join('');
  for(const n of FL)h+=`<tr><td>${esc(UIH.flag_labels[n]||n)}</td><td>${yn(fl(n))}</td></tr>`;
  const tb=PAT.tile_bank[i];if(tb)h+=`<tr><td>I/O bank (from its pins)</td><td>${esc(tb[0])}${tb[1]?' (mixed)':''}</td></tr>`;
  return h+'</table>'}
 function imgHtml(i){const tot=IM.sv[i]+IM.se[i]+IM.su[i];
  return `<b>X${tx(i)} Y${ty(i)}</b> &nbsp;${KIND[T.kind[i]]}<table><tr><td>Cells in tile</td><td>${IM.cells[i].toLocaleString()}</td></tr><tr><td>Image set bits</td><td>${IM.set[i].toLocaleString()} (${pc(IM.set[i],IM.cells[i])})</td></tr>
  <tr><td>verified / evidence / unknown set</td><td>${IM.sv[i]} / ${IM.se[i]} / ${IM.su[i]}</td></tr><tr><td>Known share of set bits</td><td>${pc(IM.sv[i]+IM.se[i],tot)}</td></tr>
  <tr><td>of which routing cells fired by decode</td><td>${IM.s2a[i]}</td></tr><tr><td>CRC-byte set bits (excluded)</td><td>${IM.so[i]}</td></tr>
  <tr><td>Known-cell capacity</td><td>${(IM.capv[i]+IM.cape[i]).toLocaleString()} (${pc(IM.capv[i]+IM.cape[i],IM.cells[i])}); verified ${IM.capv[i]}</td></tr></table>`+breakdown(i)}
 function drawBm(){const i=bsel;if(i<0||!CT||!imgOn())return;const off=IM.tp[IM.tmpl[i]][0],so=SOFF[i],w=IM.w[i];
  const z=+$('csz').value;bsc=z||Math.max(1,Math.min(14,Math.floor(900/w)));
  bm.width=w*bsc;bm.height=VP*bsc;const tint=chk('tint'),only=chk('onlyset');
  bx.fillStyle=css('--card');bx.fillRect(0,0,bm.width,bm.height);
  const col={};for(const k in TV)col[k]=css(TV[k]);
  for(let c=0;c<w;c++)for(let r=0;r<VP;r++){const k=c*VP+r,cl=CT[off+k];if(!cl)continue;const s=bit(so,k),tr=CL[cl-1][1];
   if(!s&&(only||!tint))continue;bx.globalAlpha=s?1:.16;bx.fillStyle=col[tr];bx.fillRect(c*bsc,(VP-1-r)*bsc,bsc>2?bsc-1:bsc,bsc>2?bsc-1:bsc)}
  bx.globalAlpha=1}
 bm.addEventListener('mousemove',e=>{const i=bsel;if(i<0||!CT)return;const rc=bm.getBoundingClientRect(),sx=bm.width/rc.width;
  const c=Math.floor((e.clientX-rc.left)*sx/bsc),r=VP-1-Math.floor((e.clientY-rc.top)*sx/bsc);if(c<0||c>=IM.w[i]||r<0||r>=VP)return;
  const k=c*VP+r,cl=CT[IM.tp[IM.tmpl[i]][0]+k],v=VP*ty(i)-VLO+r,fr=IM.fa[i]+c;
  $('bmi').innerHTML=cl?`frame ${fr}, v ${v} (tile row ${r}): class <b>${CL[cl-1][0]}</b> ${esc(CL[cl-1][2])} [${{V:'verified',E:'evidence',U:'unknown',O:'overhead'}[CL[cl-1][1]]}], ${bit(SOFF[i],k)?'<b>set</b>':'clear'}`:`frame ${fr}, v ${v}: not owned by this tile`});
 function hoverHtml(i){return imgOn()&&(ST.tab==='known'||(ST.tab==='chip'&&chk('lKnown')))?imgHtml(i):dieHtml(i)}
 function inspect(){const i=ST.sel.tile,on=imgOn();
  $('ititle').textContent=i<0?'click a tile on the map':`X${tx(i)} Y${ty(i)} ${KIND[T.kind[i]]}`+(on?`: frames ${IM.fa[i]}..${IM.fa[i]+IM.w[i]-1}, ${IM.w[i]} x ${VP} cells`:'');
  $('idie').innerHTML=i<0?'':dieHtml(i).replace(/^<b>.*?<\/b>[^<]*/,'');
  const k=i+':'+(CT?1:0)+':'+on;bsel=i;if(k!==bkey){bkey=k;drawBm()}}
 return {init,hoverHtml,inspect,drawBm}})();

// ======================= package geometry (matrix or perimeter), shared by the package SVG and the chip canvas =======================
const PKG=(()=>{
 if(!PERI){const PK=22,L=34;return {W:NCOL*PK+2*L,H:NROW*PK+2*L,PK,L,rad:PK*.4,field:{x:L,y:L,w:NCOL*PK,h:NROW*PK},
  pos(i,bt){const cl=PR[i][F.cell],c=cl%NCOL,j=Math.floor(cl/NCOL);return[L+((bt?c:NCOL-1-c)+.5)*PK,L+(j+.5)*PK]},side:()=>null}}
 const n=PK0.per_side,PP=15,S=n*PP,M=82,ring=13,sides=PK0.sides;
 return {W:S+2*M,H:S+2*M,PK:PP,L:M,rad:PP*.33,field:{x:M,y:M,w:S,h:S},n,S,M,ring,sides,
  side:i=>sides[Math.floor(PR[i][F.cell]/n)],
  pos(i){const p=PR[i][F.cell],s=sides[Math.floor(p/n)],f=(p%n+.5)*PP;
   return s==='left'?[M-ring,M+f]:s==='bottom'?[M+f,M+S+ring]:s==='right'?[M+S+ring,M+S-f]:[M+S-f,M-ring]}}})();
const nm=i=>ST.match===null||ST.match.has(i);

// ======================= position sentences (4b): numbers come from the payload =======================
const Pos=(()=>{
 const ord=(s)=>s;
 const corner=(a,b)=>({'left|top':'top-left','top|left':'top-left','left|bottom':'bottom-left','bottom|left':'bottom-left','right|bottom':'bottom-right','bottom|right':'bottom-right','right|top':'top-right','top|right':'top-right'}[a+'|'+b]);
 const cap=s=>s[0].toUpperCase()+s.slice(1),pl=(n,w)=>`${n} ${w}${n==1?'':'s'}`;
 function pkg(i){const g=GEO[i].pkg;
  if(g.k==='p'){const sd=PK0.sides,si=sd.indexOf(g.side),prev=sd[(si+3)%4],next=sd[(si+1)%4],c0=corner(prev,g.side),c1=corner(g.side,next);
   return `${cap(g.side)} side, pin ${g.i+1} of ${g.n} on this side. ${pl(g.i,'pin')} to the ${c0} corner${g.side==='left'?' (pin 1 side)':''}, ${pl(g.n-1-g.i,'pin')} to the ${c1} corner. ${pl(g.around,'pin')} from pin 1 counting around (${g.total-g.around} the other way). View: top view.`}
  const bt=VIEW()==='b',L=bt?g.l:g.rt,R=bt?g.rt:g.l,rowL=GR.letters[g.r];
  return `Row ${rowL} (${g.r+1} of ${g.nr}), column ${g.c+1} (${g.c+1} of ${g.nc}). Along the row: ${pl(L,'ball')} to the left edge, ${R} to the right edge. Along the column: ${pl(g.u,'ball')} to the top edge, ${g.d} to the bottom edge. Ring depth ${g.ring} (0 = outer ring). Nearest corner: ${g.corner} (${pl(g.cdr,'row')} and ${pl(g.cdc,'column')} away). View: ${bt?'Bottom view (A1 top-left)':'Top view (mirrored, A1 top-right)'}.`}
 function die(i){const d=GEO[i].die;if(!d)return '';const f=FLIP(),L=f?d.r:d.l,R=f?d.l:d.r;
  return `Die tile X${d.x} Y${d.y}${d.edge?' ('+d.edge+' edge)':''}: ${pl(L,'tile')} to the left die edge, ${R} to the right, ${d.t} to the top, ${d.b} to the bottom (die seen from the ${f?'bottom, flip-chip mirrored':'top surface'}).`}
 function html(i){return `<div class="posb"><b>Position</b><div>${esc(pkg(i))}</div>${GEO[i].die?`<div>${esc(die(i))}</div>`:''}</div>`}
 return {html,pkg,die}})();

// ======================= package view (SVG) =======================
const PkgView=(()=>{
 const {W,H,PK,L}=PKG,NS='http://www.w3.org/2000/svg',svg=$('pk');
 svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
 const el=(t,a,p)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);(p||svg).appendChild(e);return e};
 const gOut=el('g',{}),gLab=el('g',{}),gBall=el('g',{}),gLink=el('line',{stroke:'var(--accent)','stroke-width':2.5,'stroke-linecap':'round'});gLink.style.display='none';
 const balls=[],at=new Map(),a1=el('path',{fill:'var(--accent)'},gOut),labs=[],plab=[];
 PR.forEach((p,i)=>at.set(p[F.cell],i));
 if(!PERI){
  el('rect',{x:L-8,y:L-8,width:NCOL*PK+16,height:NROW*PK+16,rx:8,fill:'none',stroke:'var(--line)','stroke-width':2},gOut);
  for(let c=0;c<NCOL;c++)for(const y of[L-12,H-L+19])labs.push([el('text',{'text-anchor':'middle',y},gLab),c]);
  GR.letters.forEach((r,j)=>{for(const x of[L-14,W-L+14])el('text',{'text-anchor':'middle',x,y:L+(j+.5)*PK+3},gLab).textContent=r});
  for(let j=0;j<NROW;j++)for(let c=0;c<NCOL;c++){const i=at.get(j*NCOL+c),e=el('circle',{r:PKG.rad},gBall);
   if(i==null){e.setAttribute('fill','none');e.setAttribute('stroke','var(--mut)');e.setAttribute('stroke-dasharray','2 2');e.setAttribute('opacity','.6');e.dataset.e=GR.letters[j]+(c+1)}else e.dataset.i=i;
   balls.push([e,j,c,i])}}
 else{
  const {M,S,n}=PKG;
  el('rect',{x:M,y:M,width:S,height:S,rx:6,fill:'var(--card)',stroke:'var(--line)','stroke-width':2},gOut);
  el('circle',{cx:M+13,cy:M+13,r:5,fill:'var(--accent)'},gOut);
  el('text',{x:M+S/2,y:M+S/2-4,'text-anchor':'middle',style:'font-size:13px'},gOut).textContent=PK0.name;
  el('text',{x:M+S/2,y:M+S/2+12,'text-anchor':'middle',style:'font-size:10px'},gOut).textContent='top view, pin 1 dot top-left';
  PR.forEach((p,i)=>{const e=el('circle',{r:PKG.rad},gBall);e.dataset.i=i;balls.push([e,0,0,i]);
   const [x,y]=PKG.pos(i),s=PKG.side(i),t=el('text',{style:'font-size:7.5px','pointer-events':'none'},gLab);
   if(s==='left'){t.setAttribute('x',x-9);t.setAttribute('y',y+2.6);t.setAttribute('text-anchor','end')}
   else if(s==='right'){t.setAttribute('x',x+9);t.setAttribute('y',y+2.6)}
   else{const yy=s==='top'?y-9:y+9;t.setAttribute('x',x+2.6);t.setAttribute('y',yy);t.setAttribute('text-anchor',s==='top'?'start':'end');t.setAttribute('transform',`rotate(-90 ${x+2.6} ${yy})`)}
   plab[i]=t})}
 const dots=PR.map(()=>null);balls.forEach(([e,j,c,i])=>{if(i!=null&&PR[i][F.tile]>=0)dots[i]=el('circle',{r:2,fill:'var(--bg)','pointer-events':'none'},gBall)});
 const ringG=el('g',{'pointer-events':'none'});
 const pos=i=>PKG.pos(i,VIEW()==='b');
 function draw(){
  const f=focusPin(),fp=f>=0?PR[f]:null,pr=f>=0?PR[f][F.pair]:-1,bt=VIEW()==='b',byRole=rad('col')==='role',R=PKG.rad;
  balls.forEach(([e,j,c,i])=>{
   if(i==null){e.setAttribute('cx',L+((bt?c:NCOL-1-c)+.5)*PK);e.setAttribute('cy',L+(j+.5)*PK);return}
   const [cx,cy]=pos(i);e.setAttribute('cx',cx);e.setAttribute('cy',cy);
   const p=PR[i],col=byRole?css('--pn'+p[F.role]):BKC(p[F.bank]),on=pinOn(i);
   e.setAttribute('opacity',!on?.08:nm(i)?1:.22);
   if(p[F.bonded]){e.setAttribute('fill',col);e.setAttribute('stroke','none')}else{e.setAttribute('fill','none');e.setAttribute('stroke',col);e.setAttribute('stroke-width',2)}
   if(dots[i]){dots[i].setAttribute('cx',cx);dots[i].setAttribute('cy',cy);dots[i].setAttribute('opacity',!on?0:nm(i)?1:.22)}
   if(plab[i]){plab[i].textContent=lbl(i).slice(0,16);plab[i].setAttribute('opacity',!on?.1:nm(i)?1:.3)}});
  ringG.remove();svg.appendChild(ringG);ringG.textContent='';
  if(fp&&chk('oBank')&&fp[F.bank]!==''){PR.forEach((p,i)=>{if(p[F.bank]===fp[F.bank]&&i!==f){const[x,y]=pos(i);el('circle',{cx:x,cy:y,r:R*1.17,fill:'none',stroke:'var(--accent)','stroke-width':1.2,opacity:.8},ringG)}})}
  gLink.style.display='none';
  if(pr>=0&&chk('oPair')){const[x1,y1]=pos(f),[x2,y2]=pos(pr);gLink.setAttribute('x1',x1);gLink.setAttribute('y1',y1);gLink.setAttribute('x2',x2);gLink.setAttribute('y2',y2);gLink.style.display='';
   svg.insertBefore(gLink,ringG);el('circle',{cx:x2,cy:y2,r:R*1.25,fill:'none',stroke:'var(--accent)','stroke-width':2.5},ringG)}
  if(ST.sel.pin<0&&ST.sel.tile>=0)(TP[ST.sel.tile]||[]).forEach(i=>{const[x,y]=pos(i);el('circle',{cx:x,cy:y,r:R*1.25,fill:'none',stroke:'var(--accent)','stroke-width':2.5},ringG)});
  ST.match&&ST.match.forEach(i=>{const[x,y]=pos(i);el('circle',{cx:x,cy:y,r:R*1.25,fill:'none',stroke:'var(--fg)','stroke-width':1.5},ringG)});
  if(f>=0){const[x,y]=pos(f);el('circle',{cx:x,cy:y,r:R*1.4,fill:'none',stroke:'var(--accent)','stroke-width':3},ringG)}
  if(!PERI){labs.forEach(([t,c])=>{t.setAttribute('x',L+((bt?c:NCOL-1-c)+.5)*PK);t.textContent=c+1});
   const cx=bt?L-8:W-L+8;a1.setAttribute('d',`M${cx} ${L-8} L${cx+(bt?1:-1)*20} ${L-8} L${cx} ${L+12} Z`);
   $('vlabel').textContent=bt?'Bottom view - ball side':'Top view - mirrored';
   $('vhint').textContent=bt?'Standard BGA pinout view: A1 top-left, as seen from the PCB side.':'Lid side, A1 top-right. Top = Bottom mirrored left-right, not rotated.'}
  else{$('vlabel').textContent=`Top view - ${PK0.name}, ${PK0.n_pins} pins`;$('vhint').textContent='Pin 1 dot top-left, numbered counter-clockwise (left side down, bottom side right, right side up, top side left).'}
  const card=$('pkgcard'),w=card.clientWidth-26,h=availH(card,50);
  svg.style.width=Math.round(Math.min(w,h*W/H)*Sizer.pkg/100)+'px';Sizer.sync()}
 const tip=$('tip'),tgt=e=>{const d=e.target.dataset;return d&&d.i!=null?+d.i:-1};
 svg.addEventListener('mousemove',e=>{const i=tgt(e),t=e.target;if(i!==ST.hov.pin){ST.hov.pin=i;render()}
  if(i>=0){tip.textContent=tipText(i);tip.style.display='block'}
  else if(t.dataset&&t.dataset.e){tip.textContent=t.dataset.e+': no pin in table';tip.style.display='block'}else tip.style.display='none';
  tip.style.left=Math.min(e.clientX+14,innerWidth-260)+'px';tip.style.top=(e.clientY+14)+'px'});
 svg.addEventListener('mouseleave',()=>{ST.hov.pin=-1;tip.style.display='none';render()});
 svg.addEventListener('click',e=>{selectPin(tgt(e));render()});
 return {draw}})();
function tipText(i){const p=PR[i],b=boardName(i);return `${p[F.ball]}  ${p[F.names][0]||ROLE[p[F.role]]}${b?'  ['+b+']':''}  bank ${p[F.bank]||'-'}`}

// ======================= chip overlay: package + die + known cells + links on one canvas =======================
const CROSS=new Set();PAT.edges.forEach(e=>e.pts.forEach(q=>{if(q[3]>0)CROSS.add(q[0])}));
const ChipView=(()=>{
 const cv=$('oc'),ctx=cv.getContext('2d'),{W,H,PK,L}=PKG,RS=2.5,BR=PKG.rad*.8;
 cv.width=W*RS;cv.height=H*RS;
 const bpos=[];let D={};
 const al=id=>(+$(id).value)/100;
 function layout(){const fl=FLIP(),fld=PKG.field;let bx,by,bw,bh;
  if(chk('oAlign')){const ins=PERI?12:PK*1.7;bx=fld.x+ins;by=fld.y+ins;bw=fld.w-2*ins;bh=fld.h-2*ins;
   if(chk('oKeep')){const a=NX/NY;if(bw/bh>a){const w2=bh*a;bx+=(bw-w2)/2;bw=w2}else{const h2=bw/a;by+=(bh-h2)/2;bh=h2}}
   const s=+$('dalign').value/100;bx+=bw*(1-s)/2;by+=bh*(1-s)/2;bw*=s;bh*=s;$('dav').textContent=Math.round(s*100)+' %'}
  else{const sc=+$('dscale').value;bw=W*sc/100;bh=bw*NY/NX;bx=(W-bw)/2;by=(H-bh)/2;$('dsv').textContent=sc+' %'}
  D={dsx:bw/NX,dsy:bh/NY,dw:bw,dh:bh,x0:bx,y0:by,fl};
  const bt=VIEW()==='b';PR.forEach((p,i)=>{bpos[i]=PKG.pos(i,bt)})}
 const tcorner=t=>{const x=tx(t),y=ty(t);return [D.x0+(D.fl?NX-1-x:x)*D.dsx,D.y0+(NY-1-y)*D.dsy]};
 const tcent=t=>{const [x,y]=tcorner(t);return [x+D.dsx/2,y+D.dsy/2]};
 const scrEdge=e=>D.fl&&(e==='left'||e==='right')?(e==='left'?'right':'left'):e;
 function path(i,strand){const b=bpos[i],t=tcent(PR[i][F.tile]),g=GEO[i].die;if(!strand||!g||!g.edge)return [b,t];
  const e=scrEdge(g.edge),o=18,n=5;
  return e==='top'?[b,[b[0],D.y0-o],[t[0],D.y0-n],t]:e==='bottom'?[b,[b[0],D.y0+D.dh+o],[t[0],D.y0+D.dh+n],t]:
   e==='left'?[b,[D.x0-o,b[1]],[D.x0-n,t[1]],t]:[b,[D.x0+D.dw+o,b[1]],[D.x0+D.dw+n,t[1]],t]}
 function link(i,strand){const q=path(i,strand);ctx.beginPath();ctx.moveTo(q[0][0],q[0][1]);for(let k=1;k<q.length;k++)ctx.lineTo(q[k][0],q[k][1]);ctx.stroke()}
 function hatch(px,py,w,h,col){ctx.save();ctx.beginPath();ctx.rect(px,py,w,h);ctx.clip();ctx.strokeStyle=col;ctx.lineWidth=1;
  for(let k=-h;k<w;k+=4){ctx.beginPath();ctx.moveTo(px+k,py+h);ctx.lineTo(px+k+h,py);ctx.stroke()}ctx.restore()}
 function dieLayer(){
  const m=rad('cdmode'),a=al('aDie');
  for(let i=0;i<NT;i++){const [px,py]=tcorner(i),tb=PAT.tile_bank[i];ctx.globalAlpha=a*(VIS[TG[i]]?1:.3);
   let fill;
   if(!VIS[TG[i]])fill=css('--line');
   else if(m==='bank'&&tb)fill=BKC(tb[0]);
   else if(m==='tier')fill=css(TIERC[T.tier[i]]);
   else if(m==='dens')fill=TileView.ramp(Math.sqrt(T.set[i]/TileView.maxSet));
   else fill=css(KCOL[TG[i]]);
   ctx.fillStyle=fill;ctx.fillRect(px,py,D.dsx+.3,D.dsy+.3);
   if(m==='bank'&&tb&&tb[1]&&VIS[TG[i]])hatch(px,py,D.dsx,D.dsy,css('--bg'))}
  ctx.globalAlpha=1}
 function knownLayer(){
  const m=rad('ckmode'),a=al('aKnown'),sw=D.dsx+.3,sh=D.dsy+.3;ctx.globalAlpha=a;
  for(let i=0;i<NT;i++){if(!VIS[TG[i]])continue;const [px,py]=tcorner(i);
   if(m==='cap'){ctx.fillStyle=TileView.ramp((IM.capv[i]+IM.cape[i])/Math.max(IM.cells[i],1));ctx.fillRect(px,py,sw,sh);continue}
   const A=IM.sv[i],B=IM.se[i],C=IM.su[i],tot=A+B+C;if(!tot)continue;let y=py+sh;
   for(const [n,c] of [[A,'--ver'],[B,'--evi'],[C,'--unk']]){const h=sh*n/tot;ctx.fillStyle=css(c);ctx.fillRect(px,y-h,sw,h);y-=h}}
  ctx.globalAlpha=1}
 function bankBlocks(){ // each bank: dashed box round its pins + its tile range on the die edge, same colour
  ctx.save();ctx.lineWidth=1.6;
  PAT.banks.forEach(b=>{const col=BKC(b.bank),ix=[];PR.forEach((p,i)=>{if(p[F.bank]===b.bank&&pinOn(i))ix.push(i)});if(!ix.length)return;
   const xs=ix.map(i=>bpos[i][0]),ys=ix.map(i=>bpos[i][1]),r=BR+3;ctx.strokeStyle=col;ctx.setLineDash([4,3]);ctx.globalAlpha=.9;
   ctx.strokeRect(Math.min(...xs)-r,Math.min(...ys)-r,Math.max(...xs)-Math.min(...xs)+2*r,Math.max(...ys)-Math.min(...ys)+2*r);ctx.setLineDash([]);
   for(const e in b.die){const [lo,hi]=b.die[e],se=scrEdge(e);ctx.lineWidth=4;ctx.beginPath();
    if(e==='top'||e==='bottom'){const f=x=>D.x0+(D.fl?NX-1-x:x)*D.dsx,a=Math.min(f(lo),f(hi)),c=Math.max(f(lo),f(hi))+D.dsx,yy=se==='top'?D.y0-3:D.y0+D.dh+3;ctx.moveTo(a,yy);ctx.lineTo(c,yy)}
    else{const f=y=>D.y0+(NY-1-y)*D.dsy,a=Math.min(f(lo),f(hi)),c=Math.max(f(lo),f(hi))+D.dsy,xx=se==='left'?D.x0-3:D.x0+D.dw+3;ctx.moveTo(xx,a);ctx.lineTo(xx,c)}
    ctx.stroke();ctx.lineWidth=1.6}});
  ctx.restore()}
 function draw(){
  layout();ctx.setTransform(RS,0,0,RS,0,0);ctx.clearRect(0,0,W,H);ctx.fillStyle=css('--card');ctx.fillRect(0,0,W,H);
  const f=focusPin(),fp=f>=0?PR[f]:null,bt=VIEW()==='b',byRole=rad('col')==='role',mt=ST.match;
  if(PERI&&chk('lPkg')){ctx.globalAlpha=al('aPkg');ctx.strokeStyle=css('--line');ctx.lineWidth=2;ctx.beginPath();ctx.roundRect(PKG.M,PKG.M,PKG.S,PKG.S,6);ctx.stroke();
   ctx.fillStyle=css('--accent');ctx.beginPath();ctx.arc(PKG.M+13,PKG.M+13,5,0,7);ctx.fill();ctx.globalAlpha=1}
  if(chk('lDie'))dieLayer();
  if(imgOn()&&chk('lKnown'))knownLayer();
  ctx.strokeStyle=css('--mut');ctx.lineWidth=1;ctx.strokeRect(D.x0,D.y0,D.dw,D.dh);
  ctx.fillStyle=css('--mut');ctx.font='9px system-ui,sans-serif';ctx.textAlign='left';ctx.textBaseline='alphabetic';
  {const t=`die (${chk('oAlign')?'aligned to the package':'schematic scale'}, ${D.fl?'flip-chip mirrored':'top surface'})`;ctx.textAlign='center';ctx.lineWidth=3;ctx.strokeStyle=css('--card');ctx.strokeText(t,D.x0+D.dw/2,D.y0+D.dh/2);ctx.fillStyle=css('--fg');ctx.fillText(t,D.x0+D.dw/2,D.y0+D.dh/2);ctx.textAlign='left'}
  if(chk('lBanks'))bankBlocks();
  // links
  if(chk('lLink')){const a=al('aLink'),st=chk('lBundle'),tint=chk('lCross'),strong=new Set(),mid=new Set();
   if(f>=0)strong.add(f);if(ST.sel.pin>=0)strong.add(ST.sel.pin);mt&&mt.forEach(i=>strong.add(i));
   [ST.sel.tile,ST.hov.tile].forEach(t=>t>=0&&(TP[t]||[]).forEach(i=>strong.add(i)));
   if(fp&&chk('oBank')&&fp[F.bank]!=='')PR.forEach((p,i)=>{if(p[F.bank]===fp[F.bank])mid.add(i)});
   const ok=i=>PR[i][F.tile]>=0&&pinOn(i);
   ctx.lineWidth=.6;ctx.globalAlpha=a*.2;PR.forEach((p,i)=>{if(ok(i)&&!strong.has(i)&&!mid.has(i)){ctx.strokeStyle=tint&&CROSS.has(i)?css('--bad'):css('--fg');link(i,st)}});
   ctx.lineWidth=1;ctx.globalAlpha=a*.55;mid.forEach(i=>{if(ok(i)&&!strong.has(i)){ctx.strokeStyle=pcol(i);link(i,st)}});
   ctx.lineWidth=1.6;ctx.globalAlpha=a;strong.forEach(i=>{if(ok(i)){ctx.strokeStyle=pcol(i);link(i,st)}});ctx.globalAlpha=1}
  // die tile marks
  const mk=(t,c,w)=>{if(t<0)return;const [px,py]=tcorner(t);ctx.strokeStyle=css(c);ctx.lineWidth=w;ctx.strokeRect(px-1,py-1,D.dsx+2,D.dsy+2)};
  const hp=new Set(mt||[]);if(ST.sel.pin>=0)hp.add(ST.sel.pin);hp.forEach(i=>mk(PR[i][F.tile],'--accent',1.2));
  if(chk('oSel'))mk(ST.sel.tile,'--accent',2);mk(ST.hov.tile,'--fg',1.5);
  // package
  if(chk('lPkg')){const a=al('aPkg');ctx.globalAlpha=a;
   if(!PERI){ctx.strokeStyle=css('--line');ctx.lineWidth=2;ctx.beginPath();ctx.roundRect(L-8,L-8,NCOL*PK+16,NROW*PK+16,8);ctx.stroke();
    ctx.fillStyle=css('--accent');const cx=bt?L-8:W-L+8;ctx.beginPath();ctx.moveTo(cx,L-8);ctx.lineTo(cx+(bt?20:-20),L-8);ctx.lineTo(cx,L+12);ctx.fill();
    ctx.fillStyle=css('--mut');ctx.textAlign='center';
    for(let c=0;c<NCOL;c++){const x=L+((bt?c:NCOL-1-c)+.5)*PK;ctx.fillText(c+1,x,L-12);ctx.fillText(c+1,x,H-L+19)}
    GR.letters.forEach((l,j)=>{const y=L+(j+.5)*PK+3;ctx.fillText(l,L-14,y);ctx.fillText(l,W-L+14,y)})}
   PR.forEach((p,i)=>{const [x,y]=bpos[i],col=byRole?css('--pn'+p[F.role]):BKC(p[F.bank]),on=pinOn(i);
    ctx.globalAlpha=a*(!on?.08:nm(i)?1:.22);ctx.beginPath();ctx.arc(x,y,BR,0,7);
    if(p[F.bonded]){ctx.fillStyle=col;ctx.fill()}else{ctx.strokeStyle=col;ctx.lineWidth=1.6;ctx.stroke()}
    if(p[F.tile]>=0){ctx.beginPath();ctx.arc(x,y,1.6,0,7);ctx.fillStyle=css('--bg');ctx.fill()}
    if(PERI){const s=PKG.side(i),t=lbl(i).slice(0,14);ctx.save();ctx.fillStyle=css('--mut');ctx.font='6.5px system-ui,sans-serif';ctx.textBaseline='middle';
     if(s==='left'){ctx.textAlign='right';ctx.fillText(t,x-8,y)}else if(s==='right'){ctx.textAlign='left';ctx.fillText(t,x+8,y)}
     else{ctx.translate(x,s==='top'?y-8:y+8);ctx.rotate(-Math.PI/2);ctx.textAlign=s==='top'?'left':'right';ctx.fillText(t,0,0)}ctx.restore()}});
   ctx.globalAlpha=1;ctx.textAlign='left';
   const ring=(i,r,c,w,al_)=>{const [x,y]=bpos[i];ctx.globalAlpha=al_||1;ctx.strokeStyle=css(c);ctx.lineWidth=w;ctx.beginPath();ctx.arc(x,y,r,0,7);ctx.stroke();ctx.globalAlpha=1};
   if(fp&&chk('oBank')&&fp[F.bank]!=='')PR.forEach((p,i)=>{if(p[F.bank]===fp[F.bank]&&i!==f)ring(i,BR*1.3,'--accent',1,.8)});
   if(fp&&fp[F.pair]>=0&&chk('oPair')){const [x1,y1]=bpos[f],[x2,y2]=bpos[fp[F.pair]];ctx.strokeStyle=css('--accent');ctx.lineWidth=2.5;ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();ring(fp[F.pair],BR*1.4,'--accent',2.5)}
   if(ST.sel.pin<0&&ST.sel.tile>=0)(TP[ST.sel.tile]||[]).forEach(i=>ring(i,BR*1.4,'--accent',2.5));
   mt&&mt.forEach(i=>ring(i,BR*1.4,'--fg',1.5));
   if(f>=0)ring(f,BR*1.6,'--accent',3)}
  $('chint').textContent=(PERI?'Top view (pin 1 top-left)':bt?'Bottom view (A1 top-left)':'Top view (mirrored, A1 top-right)')+'; die '+(D.fl?'flip-chip mirrored':'top surface')+(chk('oAlign')?'; die aligned to the package ring.':'; die scale is schematic.');
  const card=$('chipcard'),w=card.clientWidth-26,h=availH(card,50);
  cv.style.width=Math.round(Math.min(w,h*W/H)*Sizer.pkg/100)+'px';Sizer.sync()}
 function pick(e){const r=cv.getBoundingClientRect(),lx=(e.clientX-r.left)*W/r.width,ly=(e.clientY-r.top)*W/r.width;
  if(chk('lPkg')){let best=-1,bd=(PKG.PK*.5)**2;PR.forEach((p,i)=>{if(!pinOn(i))return;const [x,y]=bpos[i],d=(x-lx)**2+(y-ly)**2;if(d<bd){bd=d;best=i}});if(best>=0)return {pin:best,tile:-1}}
  if(chk('lDie')||(imgOn()&&chk('lKnown'))){let x=Math.floor((lx-D.x0)/D.dsx),y=NY-1-Math.floor((ly-D.y0)/D.dsy);if(D.fl)x=NX-1-x;
   if(lx>=D.x0&&ly>=D.y0&&lx<D.x0+D.dw&&ly<D.y0+D.dh&&x>=0&&x<NX&&y>=0&&y<NY)return {pin:-1,tile:x*NY+y}}
  return {pin:-1,tile:-1}}
 const tip=$('tip');
 cv.addEventListener('mousemove',e=>{const h=pick(e);if(h.pin!==ST.hov.pin||h.tile!==ST.hov.tile){ST.hov=h;render()}
  if(h.pin>=0){tip.textContent=tipText(h.pin);tip.style.display='block';tip.style.left=Math.min(e.clientX+14,innerWidth-260)+'px';tip.style.top=(e.clientY+14)+'px'}else tip.style.display='none'});
 cv.addEventListener('mouseleave',()=>{ST.hov={tile:-1,pin:-1};tip.style.display='none';render()});
 cv.addEventListener('click',e=>{const h=pick(e);if(h.pin>=0)selectPin(h.pin);else selectTile(h.tile);render()});
 return {draw}})();

// ======================= pattern panel (4d): per die edge sentence + scatter, per bank table =======================
const PatView=(()=>{
 const SZ=96,pts=new Map();
 function init(){let h=`<div class="note" style="margin:0 0 6px">Frame: package in ${esc(PAT.frame.pkg)}, die from the ${esc(PAT.frame.die)}. Correlation = Spearman rank correlation of the pin position along the package against the die tile position along the die edge; crossings = pin pairs whose order is inverted.</div>`;
  PAT.edges.forEach((e,k)=>{h+=`<div class="pe"><div>${esc(e.sentence)}</div>`;
   if(e.n)h+=`<svg class="sc" id="sc${k}" viewBox="0 0 ${SZ} ${SZ}" role="img" aria-label="${e.edge} scatter"></svg><div class="note" style="margin:0">x: pin position along the package (${e.axis}); y: die tile position along the ${e.edge} edge. Dots on a rising diagonal = same order; falling = reversed; steps = bank-wise jumps.</div>`;
   h+='</div>'});
  h+=`<table class="num"><tr><th>bank</th><th>balls</th><th>with site</th><th>die edge: tile range</th><th>package</th></tr>`+PAT.banks.map(b=>`<tr><td><span class="sw" style="background:${BKC(b.bank)};margin-right:4px"></span>${esc(b.bank)}</td><td>${b.balls}</td><td>${b.with_site}</td><td style="text-align:left">${Object.keys(b.die).map(e=>e+' '+b.die[e][0]+'-'+b.die[e][1]).join('; ')||'-'}</td><td style="text-align:left">${esc(b.pkg)}</td></tr>`).join('')+'</table>';
  $('patbody').innerHTML=h;
  const NS='http://www.w3.org/2000/svg';
  PAT.edges.forEach((e,k)=>{const sv=$('sc'+k);if(!sv)return;
   const ln=(x1,y1,x2,y2)=>{const l=document.createElementNS(NS,'line');for(const [a,b] of Object.entries({x1,y1,x2,y2,stroke:'var(--line)'}))l.setAttribute(a,b);sv.appendChild(l)};
   ln(4,SZ-4,SZ-4,SZ-4);ln(4,4,4,SZ-4);
   e.pts.forEach(q=>{const c=document.createElementNS(NS,'circle');c.setAttribute('cx',4+q[1]*(SZ-8));c.setAttribute('cy',SZ-4-q[2]*(SZ-8));c.setAttribute('r',2);c.dataset.i=q[0];c.dataset.b=PR[q[0]][F.bank];
    c.addEventListener('mouseenter',()=>{ST.hov.pin=q[0];render()});c.addEventListener('mouseleave',()=>{ST.hov.pin=-1;render()});c.addEventListener('click',()=>{selectPin(q[0]);render()});
    sv.appendChild(c);(pts.get(q[0])||pts.set(q[0],[]).get(q[0])).push(c)})})}
 function update(){document.querySelectorAll('#patbody circle').forEach(c=>{const i=+c.dataset.i,f=focusPin()===i;
   c.setAttribute('fill',BKC(c.dataset.b));c.setAttribute('r',f?4:2);c.setAttribute('stroke',f?css('--accent'):'none');c.setAttribute('stroke-width',2);c.setAttribute('opacity',pinOn(i)?(nm(i)?1:.3):.1)})}
 return {init,update}})();

// ======================= panels: pins, search, lists, filters, inset =======================
const Panels=(()=>{
 const pinRow=i=>{const p=PR[i],b=boardName(i);return `<div class="row" data-i="${i}"><span class="dot${p[F.bonded]?'':' nb'}" style="background:${pcol(i)};border-color:${pcol(i)}"></span><b>${esc(p[F.ball])}</b><span class="m">${b?esc(b)+' / ':''}${esc(p[F.bank]||'-')} / ${esc(p[F.side]||'-')} / ${esc(p[F.names].join(', ')||ROLE[p[F.role]])}${p[F.tile]<0?'':' / X'+p[F.x]+' Y'+p[F.y]}</span></div>`};
 function pinHtml(i,links){const p=PR[i],src=G.pins.src[p[F.src]],c=pcol(i),pt=p[F.pair],t=p[F.tile],b=BRD&&BRD[i];
  let h=`<div class="pin"><b style="font-size:15px">${esc(p[F.ball])}</b> <span class="dot${p[F.bonded]?'':' nb'}" style="background:${c};border-color:${c}"></span> ${ROLE[p[F.role]]}${p[F.bonded]?'':' (not bonded)'}`+Pos.html(i)+'<table>'+
  (b?`<tr><td>Board name</td><td><b>${esc(b.name||'-')}</b></td></tr>`+(b.sig?`<tr><td>Board signal</td><td>${esc(b.sig)}</td></tr>`:'')+(b.net?`<tr><td>Board net</td><td>${esc(b.net)}</td></tr>`:'')+(b.dir?`<tr><td>Board direction</td><td>${esc(b.dir)}${b.conf?' (confidence '+esc(b.conf)+')':''}</td></tr>`:'')+(b.desc?`<tr><td>Board note</td><td>${esc(b.desc)}</td></tr>`:''):'')+
  `<tr><td>Pad number</td><td>${p[F.pad]==null?'-':p[F.pad]}</td></tr><tr><td>Bank / side</td><td>${esc(p[F.bank]||'-')} / ${esc(p[F.side]||'-')}</td></tr>`+
  `<tr><td>Die site</td><td>${t<0?SITE[siteOf(p)]:`${esc(p[F.site])} (tile X${p[F.x]} Y${p[F.y]}, z${p[F.z]})`}</td></tr>`+
  `<tr><td>I/O type</td><td>${esc(p[F.type]||'-')}</td></tr><tr><td>Vendor names</td><td>${p[F.names].length?p[F.names].map(esc).join(', '):'-'}</td></tr><tr><td>IBIS net</td><td>${esc(p[F.ibis]||'-')}</td></tr>`+
  `<tr><td>Special</td><td>${SP[p[F.role]]}</td></tr><tr><td>Usage default</td><td>${esc(p[F.usage]||'-')}</td></tr>`+
  (pt>=0?`<tr><td>Pair partner</td><td><a href="#" data-act="pin" data-i="${pt}">${esc(PR[pt][F.ball])}</a></td></tr>`:'')+`</table>`+
  (links?`<div class="note">${t>=0&&ST.tab==='pkg'?`<a href="#" data-act="die" data-i="${i}">show on die</a>`:''}${ST.tab!=='pkg'?`<a href="#" data-act="pkg" data-i="${i}">show on package</a>`:''}</div>`:'')+
  `<details><summary class="note">source fields</summary><table>${Object.keys(src).map(k=>`<tr><td>${esc(k)}</td><td>${src[k].map(esc).join(', ')}</td></tr>`).join('')}</table></details>`;
  for(const x of p[F.conflicts])h+=`<div class="bad">conflict in ${esc(x.field)}: ${Object.keys(x.values).map(s=>esc(s)+' = '+esc(JSON.stringify(x.values[s]))).join('; ')}</div>`;
  return h+'</div>'}
 function pinsel(){ // hover wins over selection; a pin card wins over a tile list
  const el=$('pinsel'),hint='<span class="note">Hover or click an IO tile (die views) or a pin (package) to inspect pins.</span>';
  let hp=-1,tl=-1;
  if(ST.tab==='pkg'){hp=ST.hov.pin>=0?ST.hov.pin:ST.sel.pin;if(hp<0)tl=ST.sel.tile}
  else if(ST.tab==='chip'){if(ST.hov.pin>=0)hp=ST.hov.pin;else if(ST.hov.tile>=0&&TP[ST.hov.tile])tl=ST.hov.tile;else if(ST.sel.pin>=0)hp=ST.sel.pin;else tl=ST.sel.tile}
  else{if(ST.hov.tile>=0&&TP[ST.hov.tile])tl=ST.hov.tile;else if(ST.sel.pin>=0)hp=ST.sel.pin;else tl=ST.sel.tile}
  if(hp>=0){const p=PR[hp];el.innerHTML=pinHtml(hp,true)+(p[F.tile]<0&&(ST.tab==='die'||ST.tab==='known')?`<div class="note">${esc(SITE[siteOf(p)])}: not drawn on the map.</div>`:'');return}
  if(tl<0||!TP[tl]){el.innerHTML=hint+(tl>=0?`<div class="note">Tile X${tx(tl)} Y${ty(tl)} has no pins.</div>`:'');return}
  const a=TP[tl];el.innerHTML=`<b>Tile X${tx(tl)} Y${ty(tl)}</b>: ${a.length} pin${a.length>1?'s':''}`+(ST.sel.tile===tl&&ST.hov.tile<0?' (selected)':'')+a.map(i=>pinHtml(i,true)).join('')}
 function lists(q){const m=q?new Set(matches(q)):null;
  [['nosite','nshead',1],['noexp','nxhead',2]].forEach(([id,hd,cls])=>{
   const all=PR.map((p,i)=>i).filter(i=>siteOf(PR[i])===cls),l=m?all.filter(i=>m.has(i)):all;
   $(hd).textContent=`${SITE[cls]} (${all.length})`+(m?` - ${l.length} match`:'');
   $(id).innerHTML=l.map(pinRow).join('')||'<div class="row"><span class="m">none</span></div>'})}
 const norm=s=>s.toLowerCase();
 function matches(q){q=norm(q.trim());if(!q)return[];const ex=[],part=[];
  PR.forEach((p,i)=>{const bn=BRD&&BRD[i]?BRD[i].names.map(norm):[];
   if(norm(p[F.ball])===q||bn.includes(q))ex.push(i);else if(norm(p[F.ball]).startsWith(q)||p[F.names].some(f=>norm(f).includes(q))||norm(p[F.ibis]).includes(q)||norm(p[F.site]).includes(q)||bn.some(f=>f.includes(q)))part.push(i)});
  return ex.concat(part)}
 function search(go){const q=$('q').value,m=matches(q),el=$('pres'),nt=$('pnote');lists(q);
  if(!q.trim()){ST.match=null;el.hidden=true;nt.textContent='';render();return}
  ST.match=new Set(m);el.hidden=false;$('pn-pins').open=true;
  el.innerHTML=m.slice(0,60).map(pinRow).join('')||'<div class="row"><span class="m">no match</span></div>';
  const on=m.filter(i=>PR[i][F.tile]>=0).length;
  nt.textContent=`${m.length} match${m.length==1?'':'es'}: ${on} with a die site, ${m.length-on} without; ringed in the active view`+(m.length>60?' (first 60 listed)':'');
  if(go&&m.length){const onmap=m.filter(i=>PR[i][F.tile]>=0);goPin(ST.tab==='pkg'||!onmap.length?m[0]:onmap[0])}else render()}
 function counts(){const bon=PR.filter(p=>p[F.bonded]).length,sc=[0,0,0];PR.forEach(p=>sc[siteOf(p)]++);const cf=PR.filter(p=>p[F.conflicts].length).length,np=PR.filter(p=>p[F.pair]>=0).length/2;
  const where=PERI?`${PR.length} pins on a ${PK0.layout} package (${PK0.per_side} per side)`:`${PR.length} balls in ${NCOL*NROW} matrix positions (${NCOL*NROW-PR.length} with no pin in table)`;
  $('pcnt').innerHTML=`<b>${PR.length}</b> ${PERI?'pins':'balls'}: ${where}. <b>${sc[0]}</b> ${esc(SITE[0])}, <b>${sc[1]}</b> ${esc(SITE[1])}, <b>${sc[2]}</b> ${esc(SITE[2])}. Bonded ${bon}. Conflicts flagged ${cf}. ${np} differential pairs.`;
  $('pinhead').textContent=`Pins (${G.device} ${PK0.name})`}
 function group(id,items,on){$(id).innerHTML=items.map(([name,n,sw,key,cid])=>`<label class="lg"><input type="checkbox" id="${cid}" data-k="${esc(key)}" checked><span class="dot" style="${sw}"></span>${esc(name)}<span class="n">${n}</span></label>`).join('');
  $(id).querySelectorAll('input').forEach(c=>{persist(c);const f=()=>{on(c.dataset.k,c.checked?1:0);render()};c.addEventListener('change',f);on(c.dataset.k,c.checked?1:0)})}
 function filters(){const rc=SP.map(()=>[0,0]);PR.forEach(p=>{rc[p[F.role]][0]++;if(p[F.tile]>=0)rc[p[F.role]][1]++});
  const sw=c=>`background:${c};border-color:${c}`;
  group('froles',SP.map((r,k)=>[ROLE[k],`${rc[k][1]} / ${rc[k][0]}`,sw(`var(--pn${k})`),k,'fr'+k]).filter((_,k)=>rc[k][0]),(k,v)=>ST.roleOn[+k]=v);
  group('fbanks',BK.map(b=>[b===''?'no bank':'Bank '+b,PR.filter(p=>p[F.bank]===b).length,'border-color:var(--mut)',b,'fb'+(b||'_')]),(k,v)=>ST.bankOn[k]=v);
  const sc=[0,0,0];PR.forEach(p=>sc[siteOf(p)]++);
  group('fsite',SITE.map((s,k)=>[s,sc[k],'border-color:var(--mut)',k,'fs'+k]),(k,v)=>ST.siteOn[+k]=v)}
 function bankDots(){$('fbanks').querySelectorAll('.dot').forEach((d,k)=>{d.style.background=d.style.borderColor=BKC(BK[k])})}
 function inset(){if(!isPk())return;
  const g=$('die'),w=180,h=Math.round(w*NY/NX),ox=10,oy=10,fl=FLIP(),f=focusPin(),p=f>=0?PR[f]:null;g.setAttribute('viewBox',`0 0 200 ${h+30}`);
  const X=x=>ox+(fl?NX-1-x:x)*w/NX+w/NX/2,Y=y=>oy+(NY-1-y)*h/NY+h/NY/2;
  let s=`<rect x="${ox}" y="${oy}" width="${w}" height="${h}" fill="none" stroke="var(--mut)" stroke-width="1.5"/><rect x="${ox+w*.08}" y="${oy+h*.1}" width="${w*.84}" height="${h*.8}" fill="none" stroke="var(--line)"/>`;
  const edge=sd=>{const m={top:[ox,oy,ox+w,oy],bottom:[ox,oy+h,ox+w,oy+h],left:[fl?ox+w:ox,oy,fl?ox+w:ox,oy+h],right:[fl?ox:ox+w,oy,fl?ox:ox+w,oy+h]}[sd];return m?`<line x1="${m[0]}" y1="${m[1]}" x2="${m[2]}" y2="${m[3]}" stroke="var(--accent)" stroke-width="5" stroke-linecap="round"/>`:''};
  let note='Select a pin (or a die tile) to see where it sits on the die.';
  const dot=(x,y)=>`<circle cx="${X(x)}" cy="${Y(y)}" r="5" fill="var(--accent)" stroke="var(--bg)" stroke-width="1.5"/>`;
  if(p){if(p[F.tile]>=0){s+=dot(p[F.x],p[F.y]);note=`${p[F.ball]}: tile X${p[F.x]} Y${p[F.y]}, ${p[F.site]}.`}
   else if(p[F.expected]){s+=edge(p[F.side]);note=`${p[F.ball]}: ${SITE[1]}; `+(p[F.side]?`${p[F.side]} edge, bank ${p[F.bank]||'-'}.`:'no side known.')}
   else note=`${p[F.ball]}: ${SITE[2]}.`}
  else if(ST.sel.tile>=0){s+=dot(tx(ST.sel.tile),ty(ST.sel.tile));note=`Selected tile X${tx(ST.sel.tile)} Y${ty(ST.sel.tile)}.`}
  s+=`<text x="${ox+w/2}" y="${h+oy+16}" text-anchor="middle">${fl?'seen from bottom (mirrored)':'seen from top surface'}</text>`;g.innerHTML=s;$('dnote').textContent=note}
 function update(){
  const t=ST.hov.tile;
  if(ST.tab!=='pkg'){$('info').innerHTML=t>=0?Img.hoverHtml(t):'Hover a tile.';Img.inspect()}
  pinsel();inset();bankDots();PatView.update()}
 function init(){
  const nm_=`${G.device} ${PK0.name}`;$('h1').textContent=`${nm_} geo explorer`;document.title=`Geo explorer ${nm_}`;
  $('pknotes').innerHTML=(PERI?PK0.notes:GR.notes).map(esc).join('<br>');
  $('q').placeholder=PERI?'Search pins: number, vendor name'+(BRD?', board name / signal / net':'')+', site':'Search pins: ball (AB12), name (DIFFIO_B1n), net, site';
  counts();filters();lists('');PatView.init();
  $('q').oninput=()=>search(false);$('q').onkeydown=e=>{if(e.key==='Enter')search(true)};
  document.addEventListener('click',e=>{ // delegated: result rows, list rows, cross links
   const a=e.target.closest('[data-act]'),r=e.target.closest('.row[data-i]');
   if(a){e.preventDefault();const i=+a.dataset.i;if(a.dataset.act==='pin'){goPin(i,false)}else{setTab(a.dataset.act);goPin(i)}return}
   if(r&&r.closest('#pres,#nosite,#noexp'))goPin(+r.dataset.i)});}
 return {init,update,pinRow}})();

// ======================= wiring =======================
function buildControls(){
 // tile-kind filter, from the payload's kind groups
 $('kinds').innerHTML=KG.map(g=>`<label><input type="checkbox" data-k="${esc(g.id)}" id="k${esc(g.id)}" checked><span class="sw" style="background:var(--k${g.slot})"></span>${esc(g.label)}</label>`).join('');
 // flag overlays (die map): only the flags this device has
 const fl={edge:'oEdge',spec:'oSpec',leout:'oLe'};
 for(const k in fl){const e=$(fl[k]),has=T.flags.includes(k);e.closest('label').hidden=!has;if(has)e.parentElement.querySelector('span').textContent=UIH.flag_labels[k]||k}
 document.querySelectorAll('[data-dens]').forEach(e=>e.textContent=UIH.set_label+' (density)');
 $('lblBoard').hidden=!BRD;
 $('dvf').hidden=!UIH.flip_chip;$('tabKnown').hidden=!IM;
 if(!BRD&&rad('lab')==='board')document.querySelector('input[name=lab][value=num]').checked=true;
 document.querySelectorAll('[data-dsg]').forEach(e=>e.hidden=!DSG);
 $('dsgnote').textContent=DSG?`Design layer: ${DSG.label}.`:'';}
function init(){
 buildControls();
 document.querySelectorAll('input[type=checkbox][id],input[type=radio][name]').forEach(e=>{if(!e.closest('#froles,#fbanks,#fsite'))persist(e)});
 document.querySelectorAll('input[data-k]').forEach(e=>{if(!e.closest('#froles,#fbanks,#fsite')){VIS[e.dataset.k]=e.checked?1:0;e.addEventListener('change',()=>{VIS[e.dataset.k]=e.checked?1:0;render()})}});
 document.querySelectorAll('input[type=checkbox],input[type=radio]').forEach(e=>{if(!e.closest('#froles,#fbanks,#fsite')&&!e.dataset.k)e.addEventListener('change',render)});
 $('oImg').disabled=!IM;
 $('imgnote').textContent=IM?`${IM.label}: tile attribution, class bitmaps and the Known cells view.`:'No image layer for this device.';
 $('oImg').addEventListener('change',()=>{$('tabKnown').disabled=!imgOn();if(ST.tab==='known'&&!imgOn())setTab('die');else renderNow()});
 $('tabKnown').disabled=!imgOn();
 document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
 document.querySelectorAll('details.pnl').forEach(d=>{const v=Store.get('pnl:'+d.id);if(v!==null)d.open=v==='1';d.addEventListener('toggle',()=>Store.set('pnl:'+d.id,d.open?'1':'0'))});
 $('pexp').onclick=()=>document.querySelectorAll('details.pnl').forEach(d=>d.open=true);
 $('pcol').onclick=()=>document.querySelectorAll('details.pnl').forEach(d=>d.open=false);
 Sizer.init();Panels.init();
 matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>{renderNow();Img.drawBm()});
 document.querySelectorAll('input.pr').forEach(e=>{persist(e);e.addEventListener('input',render)});
 const t=Store.get('tab');setTab(TABS_OK(t)?t:'die');
 Img.init()}
function TABS_OK(t){return t==='die'||t==='pkg'||t==='chip'||(t==='known'&&imgOn())}
window.geo={G,ST,setTab,selectPin,selectTile,goPin,render:renderNow,Pos};   // handle for tests and console use
init();
