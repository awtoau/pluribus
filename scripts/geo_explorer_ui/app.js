'use strict';
const G=__DATA__;
// ======================= core: data access, store, state =======================
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const Store={get(k){try{return localStorage.getItem('geo-x:'+k)}catch(e){return null}},set(k,v){try{localStorage.setItem('geo-x:'+k,v)}catch(e){}}};
const T=G.tiles,NX=T.nx,NY=T.ny,NT=NX*NY,P=G.pins,PR=P.rows,SP=P.roles,IM=G.image,GR=G.grid,VP=G.geom.vpitch,VLO=G.geom.vband_lo;
const F=Object.fromEntries(P.cols.map((c,i)=>[c,i]));          // pin row field index by name
const TP=G.xref.tile_pins;                                      // tile index -> [pin index]
const tx=i=>Math.floor(i/NY),ty=i=>i%NY;
const KIND=T.kinds,grp=k=>(k==='IOL'||k==='IOR'||k==='IOROW')?'IO':k;
const TG=Array.from({length:NT},(_,i)=>grp(KIND[T.kind[i]]));
const ROLE=["user I/O","config","JTAG","clock","transceiver","reference","power","ground","NC"];
const SITE=["with die site","no site yet","no site expected (supply / NC)"];
const siteOf=p=>p[F.tile]>=0?0:(p[F.expected]?1:2);
const BK=[...new Set(PR.map(p=>p[F.bank]))].sort((a,b)=>(a===''?1:0)-(b===''?1:0)||a.localeCompare(b,undefined,{numeric:true}));
const PTL=Object.keys(TP).map(k=>[+k,TP[k]]);
const NCOL=GR.cols,NROW=GR.letters.length;
const PVARS=['--bg','--fg','--mut','--card','--line','--ver','--evi','--unk','--ovh','--bad','--lab','--m9k','--mul','--io','--accent','--bkl'].concat(SP.map((_,i)=>'--pn'+i));
const PAL={};function readPal(){const cs=getComputedStyle(document.documentElement);PVARS.forEach(v=>PAL[v]=cs.getPropertyValue(v).trim())}
const css=n=>PAL[n];
const chk=id=>$(id).checked;
const rad=n=>{const e=document.querySelector(`input[name=${n}]:checked`);return e?e.value:null};
const imgOn=()=>!!IM&&chk('oImg');
// persisted inputs: checkbox by id, radio by name
function persist(el){
 if(el.type==='checkbox'){const k='c:'+el.id,v=Store.get(k);if(v!==null)el.checked=v==='1';el.addEventListener('change',()=>Store.set(k,el.checked?'1':'0'))}
 else if(el.type==='radio'){const k='r:'+el.name,v=Store.get(k);if(v!==null)el.checked=el.value===v;el.addEventListener('change',()=>{if(el.checked)Store.set(k,el.value)})}}
const ST={tab:'die',sel:{tile:-1,pin:-1},hov:{tile:-1,pin:-1},match:null,roleOn:SP.map(()=>1),bankOn:Object.fromEntries(BK.map(b=>[b,1])),siteOn:[1,1,1]};
const VIS={LAB:1,M9K:1,MUL:1,IO:1};
const pinOn=i=>{const p=PR[i];return ST.roleOn[p[F.role]]&&ST.bankOn[p[F.bank]]&&ST.siteOn[siteOf(p)]};
const pcol=i=>css('--pn'+PR[i][F.role]);
const BKC=b=>b===''?css('--mut'):`hsl(${Math.round(360*BK.indexOf(b)/BK.length)} 65% ${css('--bkl')})`;

// ======================= selection (shared by all views) =======================
function selectPin(i){ST.sel={pin:i,tile:i>=0?PR[i][F.tile]:-1}}
function selectTile(t){ST.sel={tile:t,pin:-1}}
function focusPin(){return ST.hov.pin>=0?ST.hov.pin:ST.sel.pin}
function matchSet(){return ST.match||new Set()}
let raf=0;function render(){if(!raf)raf=requestAnimationFrame(()=>{raf=0;renderNow()})}
function renderNow(){readPal();applyVis();if(ST.tab==='pkg')PkgView.draw();else TileView.draw();Panels.update()}
function applyVis(){document.querySelectorAll('[data-tabs],[data-needs]').forEach(e=>{
 const t=e.dataset.tabs,n=e.dataset.needs;e.hidden=(t&&!t.split(' ').includes(ST.tab))||(n==='img'&&!imgOn())})}
function setTab(t){if(t==='known'&&!imgOn())t='die';ST.tab=t;ST.hov={tile:-1,pin:-1};Store.set('tab',t);
 document.querySelectorAll('.tabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===t?'true':'false'));
 Sizer.sync();renderNow()}
function goPin(i,zoom){ // select a pin and bring it into view in the active view
 selectPin(i);const t=PR[i][F.tile];
 if(ST.tab!=='pkg'&&t>=0){VIS.IO=1;$('kIO').checked=true;if(zoom!==false)Sizer.atLeast(40);renderNow();TileView.reveal(t)}
 else{renderNow();if(ST.tab==='pkg'){const b=$('pkgcard').getBoundingClientRect();if(b.top<0||b.top>innerHeight)$('pkgcard').scrollIntoView({block:'center'})}}}

// ======================= size: one slider + Fit for the active view =======================
const Sizer={tiles:{fit:true,px:10},pkg:58,
 init(){const a=+Store.get('size-tiles');if(a>=4&&a<=56){this.tiles.fit=false;this.tiles.px=a}const b=+Store.get('size-pkg');if(b>=30&&b<=100)this.pkg=b;
  $('zoom').oninput=e=>this.set(+e.target.value);$('fitbtn').onclick=()=>this.set(ST.tab==='pkg'?100:TileView.fitPx());addEventListener('resize',()=>render())},
 set(v){if(ST.tab==='pkg'){this.pkg=Math.max(30,Math.min(100,v));Store.set('size-pkg',this.pkg)}else{this.tiles.fit=false;this.tiles.px=Math.max(4,Math.min(56,v));Store.set('size-tiles',this.tiles.px)}this.sync();renderNow()},
 atLeast(v){if(this.tiles.px<v||this.tiles.fit){this.tiles.fit=false;this.tiles.px=Math.max(this.tiles.px,v);Store.set('size-tiles',this.tiles.px)}},
 sync(){const z=$('zoom');if(ST.tab==='pkg'){z.min=30;z.max=100;z.value=this.pkg;$('zv').textContent=this.pkg+' %'}else{z.min=4;z.max=56;z.value=this.tiles.px;$('zv').textContent=this.tiles.px+' px'}}};

// ======================= tile views (Die map + Known cells share one canvas) =======================
const TileView=(()=>{
 const cv=$('c'),ctx=cv.getContext('2d'),M=2;let TS=10;
 const maxSet=Math.max(...T.set),maxDens=IM?Math.max(...IM.cells.map((c,i)=>c?IM.set[i]/c:0)):1;
 const ramp=f=>{f=Math.max(0,Math.min(1,f));const a=[247,247,240],b=[34,70,160];return `rgb(${a.map((x,i)=>Math.round(x+(b[i]-x)*f)).join(',')})`};
 const KCOL={LAB:'--lab',M9K:'--m9k',MUL:'--mul',IO:'--io'};
 const TIERC=['--ver','--evi','--unk'];
 function fitPx(){const card=cv.parentElement,w=card.clientWidth-26,top=card.getBoundingClientRect().top;const h=Math.max(360,innerHeight-Math.max(top,0)-28);return Math.max(4,Math.min(56,Math.floor(Math.min((w-2*M)/NX,(h-2*M)/NY))))}
 function resize(){if(Sizer.tiles.fit)Sizer.tiles.px=Math.max(4,Math.round(fitPx()*.58));TS=Sizer.tiles.px;Sizer.sync();
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
  if(!chk('oPins')||!VIS.IO)return;
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
   if(m==='tier')h=['verified','evidence','unknown'].map((x,i)=>`<label style="cursor:default"><span class="sw" style="background:${css(TIERC[i])}"></span>${x}</label>`).join('');
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
 return {draw,reveal,fitPx,tileAt}})();

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
 function dieHtml(i){const f=T.flag[i];
  return `<b>X${tx(i)} Y${ty(i)}</b> &nbsp;${KIND[T.kind[i]]}<table><tr><td>Evidence tier</td><td>${T.tiers[T.tier[i]]}</td></tr><tr><td>Cells in tile band</td><td>${T.cells[i].toLocaleString()}</td></tr><tr><td>Verified cells</td><td>${T.ver[i]} (${(100*T.ver[i]/T.cells[i]).toFixed(1)}%)</td></tr><tr><td>Example image set bits</td><td>${T.set[i]}</td></tr><tr><td>Die-edge tile</td><td>${f&1?'yes':'no'}</td></tr><tr><td>Specimen LAB</td><td>${f&2?'yes':'no'}</td></tr><tr><td>LE-output grid</td><td>${f&4?'yes':'no'}</td></tr></table>`}
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
 function hoverHtml(i){return ST.tab==='known'&&imgOn()?imgHtml(i):dieHtml(i)}
 function inspect(){const i=ST.sel.tile,on=imgOn();
  $('ititle').textContent=i<0?'click a tile on the map':`X${tx(i)} Y${ty(i)} ${KIND[T.kind[i]]}`+(on?`: frames ${IM.fa[i]}..${IM.fa[i]+IM.w[i]-1}, ${IM.w[i]} x ${VP} cells`:'');
  $('idie').innerHTML=i<0?'':dieHtml(i).replace(/^<b>.*?<\/b>[^<]*/,'');
  const k=i+':'+(CT?1:0)+':'+on;bsel=i;if(k!==bkey){bkey=k;drawBm()}}
 return {init,hoverHtml,inspect,drawBm}})();

// ======================= package view (SVG) =======================
const PkgView=(()=>{
 const PK=22,L=34,W=NCOL*PK+2*L,H=NROW*PK+2*L,NS='http://www.w3.org/2000/svg',svg=$('pk');
 svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
 const el=(t,a,p)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);(p||svg).appendChild(e);return e};
 const gOut=el('g',{}),gLab=el('g',{}),gBall=el('g',{}),gLink=el('line',{stroke:'var(--accent)','stroke-width':2.5,'stroke-linecap':'round'});gLink.style.display='none';
 el('rect',{x:L-8,y:L-8,width:NCOL*PK+16,height:NROW*PK+16,rx:8,fill:'none',stroke:'var(--line)','stroke-width':2},gOut);
 const a1=el('path',{fill:'var(--accent)'},gOut),labs=[];
 for(let c=0;c<NCOL;c++)for(const y of[L-12,H-L+19])labs.push([el('text',{'text-anchor':'middle',y},gLab),c]);
 GR.letters.forEach((r,j)=>{for(const x of[L-14,W-L+14])el('text',{'text-anchor':'middle',x,y:L+(j+.5)*PK+3},gLab).textContent=r});
 const at=new Map();PR.forEach((p,i)=>at.set(p[F.cell],i));
 const balls=[];
 for(let j=0;j<NROW;j++)for(let c=0;c<NCOL;c++){const i=at.get(j*NCOL+c),e=el('circle',{r:PK*.4},gBall);
  if(i==null){e.setAttribute('fill','none');e.setAttribute('stroke','var(--mut)');e.setAttribute('stroke-dasharray','2 2');e.setAttribute('opacity','.6');e.dataset.e=GR.letters[j]+(c+1)}else e.dataset.i=i;
  balls.push([e,j,c,i])}
 const dots=PR.map(()=>null);balls.forEach(([e,j,c,i])=>{if(i!=null&&PR[i][F.tile]>=0)dots[i]=el('circle',{r:2,fill:'var(--bg)','pointer-events':'none'},gBall)});
 const xOf=c=>L+((rad('view')==='b'?c:NCOL-1-c)+.5)*PK,yOf=j=>L+(j+.5)*PK,ringG=el('g',{'pointer-events':'none'});
 const pos=i=>{const cl=PR[i][F.cell];return[xOf(cl%NCOL),yOf(Math.floor(cl/NCOL))]};
 const nm=i=>ST.match===null||ST.match.has(i);
 function draw(){
  const f=focusPin(),fp=f>=0?PR[f]:null,pr=f>=0?PR[f][F.pair]:-1,bt=rad('view')==='b',byRole=rad('col')==='role';
  balls.forEach(([e,j,c,i])=>{const cx=xOf(c),cy=yOf(j);e.setAttribute('cx',cx);e.setAttribute('cy',cy);if(i==null)return;
   const p=PR[i],col=byRole?css('--pn'+p[F.role]):BKC(p[F.bank]),on=pinOn(i);
   e.setAttribute('opacity',!on?.08:nm(i)?1:.22);
   if(p[F.bonded]){e.setAttribute('fill',col);e.setAttribute('stroke','none')}else{e.setAttribute('fill','none');e.setAttribute('stroke',col);e.setAttribute('stroke-width',2)}
   if(dots[i]){dots[i].setAttribute('cx',cx);dots[i].setAttribute('cy',cy);dots[i].setAttribute('opacity',!on?0:nm(i)?1:.22)}});
  ringG.remove();svg.appendChild(ringG);ringG.textContent='';
  if(fp&&chk('oBank')&&fp[F.bank]!==''){PR.forEach((p,i)=>{if(p[F.bank]===fp[F.bank]&&i!==f){const[x,y]=pos(i);el('circle',{cx:x,cy:y,r:PK*.47,fill:'none',stroke:'var(--accent)','stroke-width':1.2,opacity:.8},ringG)}})}
  gLink.style.display='none';
  if(pr>=0&&chk('oPair')){const[x1,y1]=pos(f),[x2,y2]=pos(pr);gLink.setAttribute('x1',x1);gLink.setAttribute('y1',y1);gLink.setAttribute('x2',x2);gLink.setAttribute('y2',y2);gLink.style.display='';
   svg.insertBefore(gLink,ringG);el('circle',{cx:x2,cy:y2,r:PK*.5,fill:'none',stroke:'var(--accent)','stroke-width':2.5},ringG)}
  if(ST.sel.pin<0&&ST.sel.tile>=0)(TP[ST.sel.tile]||[]).forEach(i=>{const[x,y]=pos(i);el('circle',{cx:x,cy:y,r:PK*.5,fill:'none',stroke:'var(--accent)','stroke-width':2.5},ringG)});
  ST.match&&ST.match.forEach(i=>{const[x,y]=pos(i);el('circle',{cx:x,cy:y,r:PK*.5,fill:'none',stroke:'var(--fg)','stroke-width':1.5},ringG)});
  if(f>=0){const[x,y]=pos(f);el('circle',{cx:x,cy:y,r:PK*.55,fill:'none',stroke:'var(--accent)','stroke-width':3},ringG)}
  labs.forEach(([t,c])=>{t.setAttribute('x',xOf(c));t.textContent=c+1});
  const cx=bt?L-8:W-L+8;a1.setAttribute('d',`M${cx} ${L-8} L${cx+(bt?1:-1)*20} ${L-8} L${cx} ${L+12} Z`);
  $('vlabel').textContent=bt?'Bottom view - ball side':'Top view - mirrored';
  $('vhint').textContent=bt?'Standard BGA pinout view: A1 top-left, as seen from the PCB side.':'Lid side, A1 top-right. Top = Bottom mirrored left-right, not rotated.';
  const card=$('pkgcard'),w=card.clientWidth-26,top=card.getBoundingClientRect().top,h=Math.max(360,innerHeight-Math.max(top,0)-70);
  svg.style.width=Math.round(Math.min(w,h*W/H)*Sizer.pkg/100)+'px';Sizer.sync()}
 const tip=$('tip'),tgt=e=>{const d=e.target.dataset;return d&&d.i!=null?+d.i:-1};
 svg.addEventListener('mousemove',e=>{const i=tgt(e),t=e.target;if(i!==ST.hov.pin){ST.hov.pin=i;render()}
  if(i>=0){const p=PR[i];tip.textContent=`${p[F.ball]}  ${p[F.names][0]||ROLE[p[F.role]]}  bank ${p[F.bank]||'-'}`;tip.style.display='block'}
  else if(t.dataset&&t.dataset.e){tip.textContent=t.dataset.e+': no pin in table';tip.style.display='block'}else tip.style.display='none';
  tip.style.left=Math.min(e.clientX+14,innerWidth-200)+'px';tip.style.top=(e.clientY+14)+'px'});
 svg.addEventListener('mouseleave',()=>{ST.hov.pin=-1;tip.style.display='none';render()});
 svg.addEventListener('click',e=>{selectPin(tgt(e));render()});
 return {draw}})();

// ======================= panels: pins, search, lists, filters, inset =======================
const Panels=(()=>{
 const pinRow=i=>{const p=PR[i];return `<div class="row" data-i="${i}"><span class="dot${p[F.bonded]?'':' nb'}" style="background:${pcol(i)};border-color:${pcol(i)}"></span><b>${esc(p[F.ball])}</b><span class="m">${esc(p[F.bank]||'-')} / ${esc(p[F.side]||'-')} / ${esc(p[F.names].join(', ')||ROLE[p[F.role]])}${p[F.tile]<0?'':' / X'+p[F.x]+' Y'+p[F.y]}</span></div>`};
 function pinHtml(i,links){const p=PR[i],src=G.pins.src[p[F.src]],c=pcol(i),pt=p[F.pair],t=p[F.tile];
  let h=`<div class="pin"><b style="font-size:15px">${esc(p[F.ball])}</b> <span class="dot${p[F.bonded]?'':' nb'}" style="background:${c};border-color:${c}"></span> ${ROLE[p[F.role]]}${p[F.bonded]?'':' (not bonded)'}<table>`+
  `<tr><td>Pad number</td><td>${p[F.pad]==null?'-':p[F.pad]}</td></tr><tr><td>Bank / side</td><td>${esc(p[F.bank]||'-')} / ${esc(p[F.side]||'-')}</td></tr>`+
  `<tr><td>Die site</td><td>${t<0?(p[F.expected]?'none yet':'none expected (supply / NC)'):`${esc(p[F.site])} (tile X${p[F.x]} Y${p[F.y]}, z${p[F.z]})`}</td></tr>`+
  `<tr><td>I/O type</td><td>${esc(p[F.type]||'-')}</td></tr><tr><td>Vendor names</td><td>${p[F.names].length?p[F.names].map(esc).join(', '):'-'}</td></tr><tr><td>IBIS net</td><td>${esc(p[F.ibis]||'-')}</td></tr>`+
  `<tr><td>Special</td><td>${SP[p[F.role]]}</td></tr><tr><td>Usage default</td><td>${esc(p[F.usage]||'-')}</td></tr>`+
  (pt>=0?`<tr><td>Pair partner</td><td><a href="#" data-act="pin" data-i="${pt}">${esc(PR[pt][F.ball])}</a></td></tr>`:'')+`</table>`+
  (links?`<div class="note">${t>=0&&ST.tab==='pkg'?`<a href="#" data-act="die" data-i="${i}">show on die</a>`:''}${ST.tab!=='pkg'?`<a href="#" data-act="pkg" data-i="${i}">show on package</a>`:''}</div>`:'')+
  `<details><summary class="note">source fields</summary><table>${Object.keys(src).map(k=>`<tr><td>${esc(k)}</td><td>${src[k].map(esc).join(', ')}</td></tr>`).join('')}</table></details>`;
  for(const x of p[F.conflicts])h+=`<div class="bad">conflict in ${esc(x.field)}: ${Object.keys(x.values).map(s=>esc(s)+' = '+esc(JSON.stringify(x.values[s]))).join('; ')}</div>`;
  return h+'</div>'}
 function pinsel(){ // hover wins over selection; a pin card wins over a tile list
  const el=$('pinsel'),hint='<span class="note">Hover or click an IO tile (die views) or a ball (package) to inspect pins.</span>';
  let hp=-1,tl=-1;
  if(ST.tab==='pkg'){hp=ST.hov.pin>=0?ST.hov.pin:ST.sel.pin;if(hp<0)tl=ST.sel.tile}
  else{if(ST.hov.tile>=0&&TP[ST.hov.tile])tl=ST.hov.tile;else if(ST.sel.pin>=0)hp=ST.sel.pin;else tl=ST.sel.tile}
  if(hp>=0){const p=PR[hp];el.innerHTML=pinHtml(hp,true)+(p[F.tile]<0&&ST.tab!=='pkg'?`<div class="note">${p[F.expected]?'No die site registered for this ball yet: not drawn on the map.':'No die site expected (supply / NC ball): not drawn on the map.'}</div>`:'');return}
  if(tl<0||!TP[tl]){el.innerHTML=hint+(tl>=0?`<div class="note">Tile X${tx(tl)} Y${ty(tl)} has no pins.</div>`:'');return}
  const a=TP[tl];el.innerHTML=`<b>Tile X${tx(tl)} Y${ty(tl)}</b>: ${a.length} pin${a.length>1?'s':''}`+(ST.sel.tile===tl&&ST.hov.tile<0?' (selected)':'')+a.map(i=>pinHtml(i,true)).join('')}
 function lists(q){const m=q?new Set(matches(q)):null;
  [['nosite','nshead',1,'no die site yet'],['noexp','nxhead',0,'no die site expected (supply / NC)']].forEach(([id,hd,ex,t])=>{
   const all=PR.map((p,i)=>i).filter(i=>PR[i][F.tile]<0&&PR[i][F.expected]==ex),l=m?all.filter(i=>m.has(i)):all;
   $(hd).textContent=`${t} (${all.length})`+(m?` - ${l.length} match`:'');
   $(id).innerHTML=l.map(pinRow).join('')||'<div class="row"><span class="m">none</span></div>'})}
 const norm=s=>s.toLowerCase();
 function matches(q){q=norm(q.trim());if(!q)return[];const ex=[],part=[];
  PR.forEach((p,i)=>{if(norm(p[F.ball])===q)ex.push(i);else if(norm(p[F.ball]).startsWith(q)||p[F.names].some(f=>norm(f).includes(q))||norm(p[F.ibis]).includes(q)||norm(p[F.site]).includes(q))part.push(i)});
  return ex.concat(part)}
 function search(go){const q=$('q').value,m=matches(q),el=$('pres'),nt=$('pnote');lists(q);
  if(!q.trim()){ST.match=null;el.hidden=true;nt.textContent='';render();return}
  ST.match=new Set(m);el.hidden=false;$('pn-pins').open=true;
  el.innerHTML=m.slice(0,60).map(pinRow).join('')||'<div class="row"><span class="m">no match</span></div>';
  const on=m.filter(i=>PR[i][F.tile]>=0).length;
  nt.textContent=`${m.length} match${m.length==1?'':'es'}: ${on} with a die site, ${m.length-on} without; ringed in the active view`+(m.length>60?' (first 60 listed)':'');
  if(go&&m.length){const onmap=m.filter(i=>PR[i][F.tile]>=0);goPin(ST.tab==='pkg'||!onmap.length?m[0]:onmap[0])}else render()}
 function counts(){const bon=PR.filter(p=>p[F.bonded]).length,nex=PR.filter(p=>siteOf(p)==2).length,site=PR.filter(p=>siteOf(p)==0).length,cf=PR.filter(p=>p[F.conflicts].length).length,np=PR.filter(p=>p[F.pair]>=0).length/2;
  $('pcnt').innerHTML=`<b>${PR.length}</b> balls in ${NCOL*NROW} matrix positions (${NCOL*NROW-PR.length} with no pin in table): <b>${site}</b> with die site, <b>${PR.length-site-nex}</b> no site yet, <b>${nex}</b> no site expected (supply / NC). Bonded ${bon}. Conflicts flagged ${cf}. ${np} differential pairs.`;
  $('pinhead').textContent=`Pins (${G.device}${G.package})`}
 function group(id,items,on){$(id).innerHTML=items.map(([name,n,sw,key,cid])=>`<label class="lg"><input type="checkbox" id="${cid}" data-k="${esc(key)}" checked><span class="dot" style="${sw}"></span>${esc(name)}<span class="n">${n}</span></label>`).join('');
  $(id).querySelectorAll('input').forEach(c=>{persist(c);const f=()=>{on(c.dataset.k,c.checked?1:0);render()};c.addEventListener('change',f);on(c.dataset.k,c.checked?1:0)})}
 function filters(){const rc=SP.map(()=>[0,0]);PR.forEach(p=>{rc[p[F.role]][0]++;if(p[F.tile]>=0)rc[p[F.role]][1]++});
  const sw=c=>`background:${c};border-color:${c}`;
  group('froles',SP.map((r,k)=>[ROLE[k],`${rc[k][1]} / ${rc[k][0]}`,sw(`var(--pn${k})`),k,'fr'+k]).filter((_,k)=>rc[k][0]),(k,v)=>ST.roleOn[+k]=v);
  group('fbanks',BK.map(b=>[b===''?'no bank':'Bank '+b,PR.filter(p=>p[F.bank]===b).length,'border-color:var(--mut)',b,'fb'+(b||'_')]),(k,v)=>ST.bankOn[k]=v);
  const sc=[0,0,0];PR.forEach(p=>sc[siteOf(p)]++);
  group('fsite',SITE.map((s,k)=>[s,sc[k],'border-color:var(--mut)',k,'fs'+k]),(k,v)=>ST.siteOn[+k]=v)}
 function bankDots(){$('fbanks').querySelectorAll('.dot').forEach((d,k)=>{d.style.background=d.style.borderColor=BKC(BK[k])})}
 // die inset (package tab)
 function inset(){if(ST.tab!=='pkg')return;
  const g=$('die'),w=180,h=Math.round(w*NY/NX),ox=10,oy=10,fl=rad('dv')==='f',f=focusPin(),p=f>=0?PR[f]:null;g.setAttribute('viewBox',`0 0 200 ${h+30}`);
  const X=x=>ox+(fl?NX-1-x:x)*w/NX+w/NX/2,Y=y=>oy+(NY-1-y)*h/NY+h/NY/2;
  let s=`<rect x="${ox}" y="${oy}" width="${w}" height="${h}" fill="none" stroke="var(--mut)" stroke-width="1.5"/><rect x="${ox+w*.08}" y="${oy+h*.1}" width="${w*.84}" height="${h*.8}" fill="none" stroke="var(--line)"/>`;
  const edge=sd=>{const m={top:[ox,oy,ox+w,oy],bottom:[ox,oy+h,ox+w,oy+h],left:[fl?ox+w:ox,oy,fl?ox+w:ox,oy+h],right:[fl?ox:ox+w,oy,fl?ox:ox+w,oy+h]}[sd];return m?`<line x1="${m[0]}" y1="${m[1]}" x2="${m[2]}" y2="${m[3]}" stroke="var(--accent)" stroke-width="5" stroke-linecap="round"/>`:''};
  let note='Select a ball (or a die tile) to see where it sits on the die.';
  const dot=(x,y)=>`<circle cx="${X(x)}" cy="${Y(y)}" r="5" fill="var(--accent)" stroke="var(--bg)" stroke-width="1.5"/>`;
  if(p){if(p[F.tile]>=0){s+=dot(p[F.x],p[F.y]);note=`${p[F.ball]}: tile X${p[F.x]} Y${p[F.y]}, ${p[F.site]}.`}
   else if(p[F.expected]){s+=edge(p[F.side]);note=`${p[F.ball]}: no die site yet; `+(p[F.side]?`${p[F.side]} edge, bank ${p[F.bank]||'-'}.`:'no side known.')}
   else note=`${p[F.ball]}: supply / NC ball, no die site expected.`}
  else if(ST.sel.tile>=0){s+=dot(tx(ST.sel.tile),ty(ST.sel.tile));note=`Selected tile X${tx(ST.sel.tile)} Y${ty(ST.sel.tile)}.`}
  s+=`<text x="${ox+w/2}" y="${h+oy+16}" text-anchor="middle">${fl?'seen from bottom (mirrored)':'seen from top surface'}</text>`;g.innerHTML=s;$('dnote').textContent=note}
 function update(){
  const t=ST.hov.tile;
  if(ST.tab!=='pkg'){$('info').innerHTML=t>=0?Img.hoverHtml(t):'Hover a tile.';Img.inspect()}
  pinsel();inset();bankDots()}
 function init(){
  $('h1').textContent=`${G.device} geo explorer`;$('pknotes').innerHTML=GR.notes.map(esc).join('<br>');
  counts();filters();lists('');
  $('q').oninput=()=>search(false);$('q').onkeydown=e=>{if(e.key==='Enter')search(true)};
  document.addEventListener('click',e=>{ // delegated: result rows, list rows, cross links
   const a=e.target.closest('[data-act]'),r=e.target.closest('.row[data-i]');
   if(a){e.preventDefault();const i=+a.dataset.i;if(a.dataset.act==='pin'){goPin(i,false)}else{setTab(a.dataset.act);goPin(i)}return}
   if(r&&r.closest('#pres,#nosite,#noexp'))goPin(+r.dataset.i)});}
 return {init,update}})();

// ======================= wiring =======================
function init(){
 document.querySelectorAll('input[type=checkbox][id],input[type=radio][name]').forEach(e=>{if(!e.closest('#froles,#fbanks,#fsite'))persist(e)});
 document.querySelectorAll('input[data-k]').forEach(e=>{if(!e.closest('#froles,#fbanks,#fsite')){VIS[e.dataset.k]=e.checked?1:0;e.addEventListener('change',()=>{VIS[e.dataset.k]=e.checked?1:0;render()})}});
 document.querySelectorAll('input[type=checkbox],input[type=radio]').forEach(e=>{if(!e.closest('#froles,#fbanks,#fsite')&&!e.dataset.k)e.addEventListener('change',render)});
 $('oImg').disabled=!IM;
 $('imgnote').textContent=IM?`${IM.label}: tile attribution, class bitmaps and the Known cells view.`:'Image layer not built (tmp/geo/image_overlay_data.json missing): run scripts/geo_image_overlay.py --image.';
 $('oImg').addEventListener('change',()=>{$('tabKnown').disabled=!imgOn();if(ST.tab==='known'&&!imgOn())setTab('die');else renderNow()});
 $('tabKnown').disabled=!imgOn();
 document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
 document.querySelectorAll('details.pnl').forEach(d=>{const v=Store.get('pnl:'+d.id);if(v!==null)d.open=v==='1';d.addEventListener('toggle',()=>Store.set('pnl:'+d.id,d.open?'1':'0'))});
 $('pexp').onclick=()=>document.querySelectorAll('details.pnl').forEach(d=>d.open=true);
 $('pcol').onclick=()=>document.querySelectorAll('details.pnl').forEach(d=>d.open=false);
 Sizer.init();Panels.init();
 matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>{renderNow();Img.drawBm()});
 const t=Store.get('tab');setTab(TABS_OK(t)?t:'die');
 Img.init()}
function TABS_OK(t){return t==='die'||t==='pkg'||(t==='known'&&imgOn())}
window.geo={G,ST,setTab,selectPin,selectTile,goPin,render:renderNow};   // handle for tests and console use
init();
