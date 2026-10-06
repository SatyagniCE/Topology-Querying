import {nextZoomScale, fitImageScale} from './viewer-controls.mjs';

const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const enc = encodeURIComponent;
const fmt = value => Number(value).toLocaleString();
const main = $('#main');
let system, current, network, graphData, routeVersion=0, libraryVersion=0, graphVersion=0, dirty=false, lastHash='', restoringHash=false;
let lib={search:'',dataset:'',device:'',offset:0};
let expandedViewer=null;

function expandButton(panel){return `<button class="button small viewer-expand" aria-label="${expandedViewer?.panel===panel?'Close expanded viewer':'Expand viewer'}">${expandedViewer?.panel===panel?'Close ⤡':'Expand ⤢'}</button>`;}
function bindExpansion(panel,onResize=()=>network?.redraw()){
  const button=$('.viewer-expand',panel);
  button.onclick=()=>{
    const dialog=$('#viewer-dialog');
    if(expandedViewer?.panel===panel){dialog.close();return;}
    if(dialog.open)dialog.close();
    const marker=document.createComment('viewer-position');panel.before(marker);
    expandedViewer={panel,marker,onResize,button};dialog.append(panel);dialog.showModal();
    document.body.classList.add('viewer-open');button.textContent='Close ⤡';button.setAttribute('aria-label','Close expanded viewer');button.focus();
    requestAnimationFrame(onResize);
  };
  if(expandedViewer?.panel===panel)expandedViewer.onResize=onResize;
}
function restoreViewer(){
  if(!expandedViewer)return;
  const {panel,marker,onResize,button}=expandedViewer;expandedViewer=null;
  marker.replaceWith(panel);document.body.classList.remove('viewer-open');
  const activeButton=$('.viewer-expand',panel)||button;
  if(activeButton?.isConnected){activeButton.textContent='Expand ⤢';activeButton.setAttribute('aria-label','Expand viewer');activeButton.focus();}
  requestAnimationFrame(onResize);
}
$('#viewer-dialog').addEventListener('close',()=>{if(!$('#viewer-dialog').open)restoreViewer();});
function closeViewer(){const dialog=$('#viewer-dialog');if(dialog.open)dialog.close();restoreViewer();}
function graphTools(){return `<div class="zoom-controls" role="group" aria-label="Graph zoom"><button class="button small" data-zoom="out" aria-label="Zoom out" title="Zoom out one step">−</button><output class="zoom-level" aria-label="Graph zoom level">—</output><button class="button small" data-zoom="in" aria-label="Zoom in" title="Zoom in one step">+</button><button class="button small" data-zoom="fit" title="Fit all visible nodes">Fit</button></div>`;}
function bindGraphTools(panel){
  const level=$('.zoom-level',panel);
  const update=()=>{if(level?.isConnected)level.textContent=network?Math.round(network.getScale()*100)+'%':'—';};
  $$('[data-zoom]',panel).forEach(button=>button.onclick=()=>{
    if(!network)return;
    if(button.dataset.zoom==='fit')network.fit({animation:{duration:180}});
    else network.moveTo({scale:nextZoomScale(network.getScale(),button.dataset.zoom==='in'?1:-1),animation:{duration:180,easingFunction:'easeInOutQuad'}});
    update();
  });
  network?.on('zoom',update);network?.on('animationFinished',update);network?.on('stabilized',update);update();
}
let queryState;
try {queryState=JSON.parse(localStorage.getItem('atlas-query')) || {};} catch {queryState={};}
queryState={mode:'cypher',query:'MATCH (c:Circuit)-[:HAS_DEVICE]->(d:Device)\nRETURN c.id AS circuit_id, count(d) AS devices\nORDER BY devices DESC\nLIMIT 20',parameters:'{}',text:'',reference:'',...queryState};
let lastResult=null;
const graphOptions={backend:'networkx',rails:false,ports:false};
const examples=[
  {name:'Circuit inventory',note:'Rank circuits by actual device count',query:'MATCH (c:Circuit)-[:HAS_DEVICE]->(d:Device)\nRETURN c.id AS circuit_id, count(d) AS devices\nORDER BY devices DESC\nLIMIT 20'},
  {name:'Inspect circuit 1004',note:'Return its devices, nets and terminal connections',query:"MATCH (c:Circuit {id: 'analoggenie:1004'})-[:HAS_DEVICE]->(d)\nMATCH (d)-[r:CONNECTED_TO]->(n:Net)\nRETURN d, r, n\nLIMIT 100"},
  {name:'NMOS mirror candidates',note:'Diode-connected reference, shared gate/source, distinct output',query:"MATCH (c:Circuit)-[:HAS_DEVICE]->(a:Device {canonical_type:'nmos'})\nMATCH (c)-[:HAS_DEVICE]->(b:Device {canonical_type:'nmos'})\nMATCH (a)-[:CONNECTED_TO {terminal:'gate'}]->(g:Net)\nMATCH (a)-[:CONNECTED_TO {terminal:'drain'}]->(g)\nMATCH (b)-[:CONNECTED_TO {terminal:'gate'}]->(g)\nMATCH (a)-[:CONNECTED_TO {terminal:'source'}]->(s:Net)\nMATCH (b)-[:CONNECTED_TO {terminal:'source'}]->(s)\nMATCH (b)-[:CONNECTED_TO {terminal:'drain'}]->(out:Net)\nWHERE a <> b AND out <> g AND s.name IN ['VSS','0','GND']\nRETURN c.id AS circuit_id, a.source_instance AS reference_device,\n       b.source_instance AS output_device, g.name AS control, out.name AS output\nORDER BY circuit_id\nLIMIT 30"},
  {name:'Topology neighbours of 1004',note:'Query the native Neo4j vector index',query:"MATCH (ref:Circuit {id:'analoggenie:1004'})\nMATCH (c:Circuit)\nSEARCH c IN (\n  VECTOR INDEX circuit_topology_idx\n  FOR ref.topology_embedding\n  LIMIT 21\n) SCORE AS score\nWITH c, ref, score WHERE c <> ref\nRETURN c.id AS circuit_id, score\nORDER BY score DESC\nLIMIT 20"}
];

async function api(path, options={}) {
  const response=await fetch(path,{headers:{'Content-Type':'application/json'},...options});
  let body;
  try {body=await response.json();} catch {throw new Error('The local service returned an unexpected response.');}
  if(!response.ok){let message=body.detail || 'Request failed';if(Array.isArray(message))message=message.map(x=>`${x.loc?.join('.')}: ${x.msg}`).join('\n');throw new Error(message);}
  return body;
}
function toast(text){$('#toast').textContent=text;$('#toast').classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.remove('show'),4000);}
function errorHTML(message){return `<div class="error" role="alert">${esc(message)}</div>`;}
function loading(text='Loading circuits…'){return `<div class="loading"><span class="spinner"></span>${esc(text)}</div>`;}
function empty(title,message){return `<div class="empty"><svg width="40" height="40" viewBox="0 0 40 40" fill="none"><rect x="7" y="7" width="26" height="26" rx="3" stroke="currentColor"/><path d="M12 20h16M20 12v16" stroke="currentColor"/></svg><h3>${esc(title)}</h3><p>${esc(message)}</p></div>`;}
function profile(stats){return Object.entries(stats.device_type_counts).slice(0,6).map(([type,n])=>`<span class="pill ${type==='nmos'?'olive':type==='pmos'?'copper':''}">${esc(type.toUpperCase())} <span class="mono">${n}</span></span>`).join('');}
function circuitURL(id,tab='graph'){return `#circuit/${enc(id)}/${tab}`;}
function openCircuit(id,tab='graph'){location.hash=circuitURL(id,tab);}
function exportJSON(data,name){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function persistQuery(){localStorage.setItem('atlas-query',JSON.stringify(queryState));}
function referenceId(value){value=value.trim();return /^\d+$/.test(value)?'analoggenie:'+value:value;}

async function updateStatus(){
  try {system=await api('/api/status');const ready=system.retrieval.state==='ready';$('#system-status').textContent=ready?`${fmt(system.indexed)} indexed · Neo4j ${system.neo4j.connected?'connected':'offline'}`:`Index ${fmt(system.indexed)} / ${fmt(system.circuits)} · ${system.retrieval.state}`;$('.status-dot').classList.toggle('warn',!ready||!system.neo4j.connected);
    if($('#library-count'))$('#library-count').textContent=fmt(system.circuits);
    if($('#library-indexed'))$('#library-indexed').textContent=fmt(system.indexed);
    if($('#system-dialog').open)renderSystem();
  }catch{$('#system-status').textContent='Local service unavailable';$('.status-dot').classList.add('warn');}
}
function renderSystem(){
  $('#system-content').innerHTML=`<div class="dialog-header"><div><div class="eyebrow">Workspace health</div><h2>Everything stays local.</h2></div><button class="button icon" id="close-system" aria-label="Close status">×</button></div><div class="dialog-body"><div class="fact-row"><span>Circuits</span><span class="mono">${fmt(system?.circuits||0)}</span></div><div class="fact-row"><span>Text embeddings</span><span class="mono">${fmt(system?.indexed||0)}</span></div><div class="fact-row"><span>Search index</span><span>${esc(system?.retrieval.state||'unknown')}</span></div><div class="fact-row"><span>Neo4j</span><span>${system?.neo4j.connected?'Connected':'Offline'}</span></div><div class="fact-row"><span>Awaiting graph sync</span><span class="mono">${system?.neo4j.pending||0}</span></div><p class="help" style="margin:20px 0">Text vectors use BGE-small locally. Topology vectors preserve typed terminal neighborhoods. User edits rebuild the search entry and synchronize to Neo4j.</p>${system?.retrieval.error?errorHTML(system.retrieval.error):''}${system?.neo4j.error?errorHTML(system.neo4j.error):''}<div style="display:flex;gap:10px"><button class="button" id="retry-index">Retry indexing</button><button class="button" id="retry-sync">Retry Neo4j sync</button></div></div>`;
  $('#close-system').onclick=()=>$('#system-dialog').close();
  $('#retry-index').onclick=async()=>{await api('/api/reindex',{method:'POST'});toast('Index rebuild queued');};
  $('#retry-sync').onclick=async()=>{await api('/api/sync',{method:'POST'});toast('Neo4j sync queued');};
}
$('#status-button').onclick=()=>{renderSystem();$('#system-dialog').showModal();};

async function renderLibrary(){
  main.innerHTML=`<section class="intro"><div><div class="eyebrow">Your circuit collection</div><h1>A place to inspect.<br>A way to discover.</h1><p>Explore analog circuits through their connections, original schematics and source netlists.</p></div><div class="library-stats"><div><strong id="library-count">${fmt(system?.circuits||3350)}</strong><span>circuits in the library</span></div><div><strong id="library-indexed">${fmt(system?.indexed||0)}</strong><span>search entries indexed</span></div></div></section><section class="panel"><div class="filterbar"><div class="search-field"><span aria-hidden="true">⌕</span><input id="library-search" aria-label="Search circuit library" placeholder="Find by ID, annotation, tag or source reference…" value="${esc(lib.search)}"><span class="key">/</span></div><select id="library-dataset" aria-label="Filter dataset"><option value="">All datasets</option><option>AnalogGenie</option><option>Uploaded</option></select><select id="library-device" aria-label="Filter device type"><option value="">All device types</option>${['nmos','pmos','npn','pnp','resistor','capacitor','inductor'].map(x=>`<option value="${x}">${x.toUpperCase()}</option>`).join('')}</select><button class="button small quiet" id="clear-filters">Reset</button></div><div id="library-results">${loading()}</div></section><p class="data-note">Existing source metadata is preserved. Detailed circuit classifications remain unannotated until supplied by a researcher.</p>`;
  $('#library-dataset').value=lib.dataset;$('#library-device').value=lib.device;
  let timer;$('#library-search').oninput=e=>{lib.search=e.target.value;lib.offset=0;clearTimeout(timer);timer=setTimeout(fetchLibrary,220);};
  for(const field of ['dataset','device'])$(`#library-${field}`).onchange=e=>{lib[field]=e.target.value;lib.offset=0;fetchLibrary();};
  $('#clear-filters').onclick=()=>{lib={search:'',dataset:'',device:'',offset:0};renderLibrary();};
  await fetchLibrary();
}
async function fetchLibrary(){
  const version=++libraryVersion;
  try{const data=await api('/api/circuits?'+new URLSearchParams({...lib,limit:30}));if(version!==libraryVersion||!$('#library-results'))return;
    const rows=data.items.map(c=>`<tr data-id="${esc(c.id)}" tabindex="0" aria-label="Inspect ${esc(c.title)}"><td><div class="circuit-cell"><span class="circuit-glyph">⌁</span><div><span class="circuit-name">${esc(c.title)}</span><span class="circuit-id">${esc(c.id)}</span></div></div></td><td class="number">${c.statistics.device_count}</td><td class="number">${c.statistics.net_count}</td><td>${c.has_schematic?'<span class="pill">Schematic</span>':'<span class="muted">—</span>'}</td><td class="arrow">↗</td></tr>`).join('');
    $('#library-results').innerHTML=(data.total?`<div class="table-wrap"><table class="library-table"><thead><tr><th>CIRCUIT</th><th>DEVICES</th><th>NETS</th><th>SOURCE</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`:empty('No circuits found','Try another ID or keyword, or clear the filters.'))+`<div class="pagination"><span>${data.total?`${fmt(data.offset+1)}–${fmt(Math.min(data.offset+30,data.total))} of ${fmt(data.total)}`:'0 circuits'}</span><div class="pagination-controls"><button class="button small" id="previous-page" ${!lib.offset?'disabled':''}>← Previous</button><button class="button small" id="next-page" ${data.offset+30>=data.total?'disabled':''}>Next →</button></div></div>`;
    $$('[data-id]',$('#library-results')).forEach(row=>{row.onclick=()=>openCircuit(row.dataset.id);row.onkeydown=e=>{if(e.key==='Enter')openCircuit(row.dataset.id);};});
    $('#previous-page').onclick=()=>{lib.offset=Math.max(0,lib.offset-30);fetchLibrary();};$('#next-page').onclick=()=>{lib.offset+=30;fetchLibrary();};
  }catch(e){if($('#library-results'))$('#library-results').innerHTML=errorHTML(e.message);}
}

function factsHTML(c){return `<aside class="inspector-sidebar"><section class="panel facts"><h3>At a glance</h3><div class="fact-row"><span>Dataset</span><span>${esc(c.dataset)}</span></div><div class="fact-row"><span>Devices</span><span class="mono">${c.statistics.device_count}</span></div><div class="fact-row"><span>Nets</span><span class="mono">${c.statistics.net_count}</span></div><div class="fact-row"><span>Terminal connections</span><span class="mono">${c.statistics.connection_count}</span></div><div class="type-profile type-list">${profile(c.statistics)}</div><div class="facts-block"><h3>External ports <span class="muted">${c.ports.length}</span></h3><div class="port-list">${c.ports.map(p=>`<span class="pill mono">${esc(p.name)}</span>`).join('')||'<span class="help">No declared ports</span>'}</div></div><div class="facts-block"><h3>Research annotation</h3><p>${esc(c.metadata.description||'No description supplied. Add an annotation in the Metadata tab.')}</p>${c.metadata.family?`<div class="type-profile" style="margin-top:10px"><span class="pill olive">${esc(c.metadata.family)}</span>${c.metadata.topology?`<span class="pill">${esc(c.metadata.topology)}</span>`:''}</div>`:''}</div><div class="fact-links"><a class="text-button" href="/api/circuits/${enc(c.id)}/record">Download circuit JSON ↗</a><a class="text-button" href="/api/circuits/${enc(c.id)}/netlist">Download source netlist ↗</a></div></section><div id="node-details"></div><p class="sidebar-note">Both graph views use the same terminal-aware circuit model. NetworkX is built locally; Neo4j reads the stored graph live.</p></aside>`;}
function setDetailsVisible(visible){
  const body=$('#detail-body'),button=$('#toggle-details');if(!body||!button)return;
  body.classList.toggle('show-details',visible);button.setAttribute('aria-expanded',String(visible));button.textContent=visible?'Hide details':'Details';
}
async function renderDetail(id,tab,version){
  main.innerHTML=loading('Opening circuit…');
  try{const c=await api(`/api/circuits/${enc(id)}`);if(version!==routeVersion)return;current=c;
    main.innerHTML=`<div class="breadcrumb"><button id="back-library">← Circuit library</button><span>/</span><span class="mono">${esc(c.id)}</span></div><div class="detail-heading"><div><div class="eyebrow">${esc(c.dataset)} / circuit ${esc(c.source_id)}</div><h1>${esc(c.title)}</h1></div><div class="detail-actions"><button class="button" id="find-similar">⌕ Find similar</button><button class="button quiet" id="query-circuit">Query this graph ↗</button>${tab!=='metadata'?'<button class="button details-toggle" id="toggle-details" aria-expanded="false" aria-controls="detail-sidebar">Details</button>':''}</div></div><div class="tabs" role="tablist">${['graph','schematic','netlist','metadata'].map(t=>`<button role="tab" aria-selected="${t===tab}" class="${t===tab?'active':''}" data-tab="${t}">${t[0].toUpperCase()+t.slice(1)}</button>`).join('')}</div><div id="detail-body"></div>`;
    $('#back-library').onclick=()=>{location.hash='#library';};$$('[data-tab]').forEach(b=>b.onclick=()=>openCircuit(id,b.dataset.tab));
    $('#find-similar').onclick=()=>{queryState.mode='similarity';queryState.reference=id;queryState.text='';lastResult=null;persistQuery();location.hash='#query';};
    $('#query-circuit').onclick=()=>{queryState.mode='cypher';queryState.query=`MATCH (c:Circuit {id: $id})-[:HAS_DEVICE]->(d)\nMATCH (d)-[r:CONNECTED_TO]->(n:Net)\nRETURN d, r, n\nLIMIT 200`;queryState.parameters=JSON.stringify({id},null,2);lastResult=null;persistQuery();location.hash='#query';};
    if(tab==='metadata')renderMetadata(c);else{
      $('#detail-body').innerHTML=`<div class="inspector-grid"><section class="panel" id="detail-panel"></section>${factsHTML(c)}</div>`;
      const aside=$('.inspector-sidebar');aside.id='detail-sidebar';aside.prepend($('#node-details'));
      $('#toggle-details').onclick=()=>setDetailsVisible(!$('#detail-body').classList.contains('show-details'));
      if(tab==='graph')renderGraphPanel(c);if(tab==='schematic')renderSchematic(c);if(tab==='netlist')renderNetlist(c);
    }
  }catch(e){if(version===routeVersion)main.innerHTML=errorHTML(e.message)+`<a class="button" href="#library">Return to library</a>`;}
}
async function renderGraphPanel(c){
  graphData=null;network?.destroy();network=null;
  const panel=$('#detail-panel');
  panel.innerHTML=`<div class="panel-heading viewer-heading"><h3>Terminal connectivity</h3><div class="viewer-actions"><div class="segmented" aria-label="Graph backend"><button id="backend-networkx" class="${graphOptions.backend==='networkx'?'active':''}">NetworkX</button><button id="backend-neo4j" class="${graphOptions.backend==='neo4j'?'active':''}">Neo4j</button></div><button class="button small" id="graph-json">JSON ↗</button>${expandButton(panel)}</div></div><div class="graph-wrap"><div class="graph-tools">${graphTools()}</div><div class="graph-canvas" id="circuit-graph">${loading('Building graph…')}</div></div><div class="graph-footer"><div class="legend"><span><i style="background:#a7bc83"></i>NMOS</span><span><i style="background:#d0a184"></i>PMOS</span><span><i style="background:#a8afa2"></i>Net</span></div><div style="display:flex;gap:15px"><label class="check-control"><input type="checkbox" id="show-rails" ${graphOptions.rails?'checked':''}>Supply rails</label><label class="check-control"><input type="checkbox" id="show-ports" ${graphOptions.ports?'checked':''}>Port nodes</label></div><span id="graph-count">Click a node to inspect</span></div>`;
  bindExpansion(panel);bindGraphTools(panel);
  for(const backend of ['networkx','neo4j'])$(`#backend-${backend}`).onclick=()=>{graphOptions.backend=backend;renderGraphPanel(c);};
  $('#show-rails').onchange=e=>{graphOptions.rails=e.target.checked;drawGraph($('#circuit-graph'),graphData);};$('#show-ports').onchange=e=>{graphOptions.ports=e.target.checked;drawGraph($('#circuit-graph'),graphData);};
  $('#graph-json').onclick=()=>{if(graphOptions.backend==='networkx'){const a=document.createElement('a');a.href=`/api/circuits/${enc(c.id)}/networkx`;a.click();}else if(graphData)exportJSON(graphData,c.source_id+'.neo4j.graph.json');};
  const version=++graphVersion;
  try{const data=await api(`/api/circuits/${enc(c.id)}/graph?backend=${graphOptions.backend}`);if(version!==graphVersion||!$('#circuit-graph'))return;graphData=data;drawGraph($('#circuit-graph'),data);}
  catch(e){if(version===graphVersion&&$('#circuit-graph'))$('#circuit-graph').innerHTML=errorHTML(e.message)+`<div style="padding:20px"><button class="button" id="use-networkx">Use NetworkX</button></div>`;$('#use-networkx')?.addEventListener('click',()=>{graphOptions.backend='networkx';renderGraphPanel(c);});}
}
function drawGraph(container,data,isResult=false){
  if(!data||!container)return;network?.destroy();container.innerHTML='';
  const role=n=>n.role||(['Net','Port'].includes(n.kind)?classifyPort(n.properties.name||''):'');
  const raw=data.nodes.filter(n=>isResult||((graphOptions.ports||n.kind!=='Port')&&(graphOptions.rails||!['supply','ground'].includes(role(n)))));
  const ids=new Set(raw.map(n=>n.id));
  const colors={nmos:'#a7bc83',pmos:'#d0a184',npn:'#b1c8a3',pnp:'#d6bda0',resistor:'#c2ad74',capacitor:'#c2ad74',inductor:'#c2ad74',diode:'#c2ad74'};
  const nodes=raw.map(n=>{const type=n.properties.canonical_type;const device=n.kind==='Device';const color=colors[type]||'#a8afa2';return {id:n.id,label:device?`${n.label}\n${(type||'device').toUpperCase()}`:n.label,shape:device?'box':n.kind==='Circuit'?'box':n.kind==='Port'?'diamond':'dot',size:n.kind==='Net'?7:12,margin:8,color:{background:device?'#282e22':n.kind==='Circuit'?'#433525':'#525b47',border:color,highlight:{background:'#414d33',border:'#e6d4ab'},hover:{background:'#343e28',border:'#e6d4ab'}},borderWidth:1.4,font:{color:device?'#dce6cb':'#b8c1aa',size:device?11:10,face:'monospace'},...(['supply','ground'].includes(role(n))?{color:{background:'#524133',border:'#d0a184'}}:{})};});
  const edges=data.edges.filter(e=>ids.has(e.from)&&ids.has(e.to)).map(e=>({id:e.id,from:e.from,to:e.to,width:1,color:{color:'#535f42',highlight:'#d1b08f',hover:'#b0be97',opacity:.7},smooth:{enabled:true,type:'dynamic',roundness:.15},title:esc(e.label),selectionWidth:2}));
  network=new vis.Network(container,{nodes:new vis.DataSet(nodes),edges:new vis.DataSet(edges)},{layout:{randomSeed:42,improvedLayout:true},physics:{solver:'barnesHut',barnesHut:{gravitationalConstant:-1800,springLength:95,springConstant:.045,damping:.3},stabilization:{iterations:240}},interaction:{hover:true,tooltipDelay:100,hideEdgesOnDrag:edges.length>300},nodes:{chosen:true},edges:{chosen:true}});
  bindGraphTools(container.closest('.panel'));
  network.once('stabilizationIterationsDone',()=>{network.setOptions({physics:false});network.fit();});
  network.on('selectNode',event=>{const node=raw.find(n=>n.id===event.nodes[0]);if(node&&!isResult)showNode(node);});
  if($('#graph-count')&&!isResult)$('#graph-count').textContent=`${raw.length} / ${data.nodes.length} nodes · ${data.truncated?'display capped · use JSON for the complete record':'drag to explore'}`;
}
function classifyPort(name){name=name.toUpperCase();if(['VDD','VCC','VDD!'].includes(name))return 'supply';if(['VSS','0','GND','VEE','VSS!'].includes(name))return 'ground';return '';}
function showNode(node){
  if(!$('#node-details'))return;let props=Object.entries(node.properties).filter(([k])=>!['id','source_instance','name','kind'].includes(k));
  const terminals=(graphData?.edges||[]).filter(e=>e.from===node.id).map(e=>({terminal:e.label,net:graphData.nodes.find(n=>n.id===e.to)?.label||e.to}));
  $('#node-details').innerHTML=`<div class="node-details"><div style="display:flex;justify-content:space-between"><h3>${esc(node.label)}</h3><button class="text-button" id="close-node">×</button></div>${props.map(([k,v])=>`<div class="fact-row"><span>${esc(k.replaceAll('_',' '))}</span><span class="mono">${esc(typeof v==='object'?JSON.stringify(v):v)}</span></div>`).join('')}${terminals.length?'<h3>Terminal → net</h3>'+terminals.map(t=>`<div class="fact-row"><span>${esc(t.terminal)}</span><span class="mono">${esc(t.net)}</span></div>`).join(''):''}<div class="help mono">${esc(node.canonical_id)}</div></div>`;
  $('#close-node').onclick=()=>{$('#node-details').innerHTML='';network?.unselectAll();};
  if(matchMedia('(max-width:760px)').matches&&!expandedViewer)setDetailsVisible(true);
}
function renderSchematic(c){
  const available=c.assets;let kind=available[0];
  function show(){
    const panel=$('#detail-panel');
    panel.innerHTML=`<div class="panel-heading viewer-heading"><h3>Original schematic</h3><div class="viewer-actions">${available.length>1?`<div class="segmented">${available.map(k=>`<button data-image="${k}" class="${kind===k?'active':''}">${k==='book'?'Source figure':'Cadence'}</button>`).join('')}</div>`:''}${expandButton(panel)}</div></div>${kind?`<div class="schematic-viewport"><div class="graph-tools"><div class="zoom-controls" role="group" aria-label="Schematic zoom"><button class="button small" data-image-zoom="out" aria-label="Zoom out">−</button><output class="zoom-level" aria-label="Schematic zoom level">—</output><button class="button small" data-image-zoom="in" aria-label="Zoom in">+</button><button class="button small" data-image-zoom="fit">Fit</button><button class="button small" data-image-zoom="original" title="Show original image size">1:1</button></div></div><div class="schematic-wrap" id="schematic-wrap"><div class="schematic-stage"><img src="/api/circuits/${enc(c.id)}/asset/${kind}" alt="Original schematic for ${esc(c.title)}" id="schematic-image"></div></div></div><div class="graph-footer"><span>Zoom to inspect · scroll to pan</span><a href="/api/circuits/${enc(c.id)}/asset/${kind}" target="_blank" rel="noopener">Open original ↗</a></div>`:empty('No schematic available','This record contains a netlist and graph. Schematic images are optional when adding a circuit.')}`;
    $$('[data-image]').forEach(b=>b.onclick=()=>{kind=b.dataset.image;show();});
    const image=$('#schematic-image'),wrap=$('#schematic-wrap');let scale=1;
    const apply=next=>{if(!image?.naturalWidth)return;const ratio=next/scale;const centerX=(wrap.scrollLeft+wrap.clientWidth/2)*ratio,centerY=(wrap.scrollTop+wrap.clientHeight/2)*ratio;scale=next;image.style.width=Math.round(image.naturalWidth*scale)+'px';$('.zoom-level',panel).textContent=Math.round(scale*100)+'%';wrap.scrollLeft=centerX-wrap.clientWidth/2;wrap.scrollTop=centerY-wrap.clientHeight/2;};
    const fit=()=>{if(wrap&&image?.naturalWidth){apply(fitImageScale(image.naturalWidth,image.naturalHeight,wrap.clientWidth,wrap.clientHeight));wrap.scrollTo(0,0);}};
    bindExpansion(panel,fit);
    if(image){image.onload=fit;image.onerror=()=>{wrap.innerHTML=errorHTML('The schematic could not be loaded.');};if(image.complete)fit();}
    $$('[data-image-zoom]',panel).forEach(button=>button.onclick=()=>{if(!image?.naturalWidth)return;const action=button.dataset.imageZoom;if(action==='fit')fit();else apply(action==='original'?1:nextZoomScale(scale,action==='in'?1:-1));});
  }show();
}
function renderNetlist(c){
  const panel=$('#detail-panel');panel.innerHTML=`<div class="panel-heading viewer-heading"><h3>Source netlist</h3><div class="viewer-actions"><button class="button small" id="copy-netlist">Copy</button><a class="button small" href="/api/circuits/${enc(c.id)}/netlist">Download ↗</a>${expandButton(panel)}</div></div><pre class="code-block">${c.netlist.split('\n').map((line,i)=>`<span class="code-line"><span class="line-number">${i+1}</span><code>${esc(line)||' '}</code></span>`).join('')}</pre><div class="graph-footer"><span>Original topology source · values preserved when supplied</span><span class="mono">${c.parser.name} ${c.parser.version}</span></div>`;
  bindExpansion(panel,()=>{});
  $('#copy-netlist').onclick=async()=>{await navigator.clipboard.writeText(c.netlist);toast('Netlist copied');};
}

function metadataFields(meta,prefix){return `<div class="form-grid"><label class="field wide">Display title<input name="title" value="${esc(meta.title)}" maxlength="200" placeholder="A useful name for this circuit"></label><label class="field wide">Basic description<textarea name="description" maxlength="6000" placeholder="Describe what is known about this circuit…">${esc(meta.description)}</textarea></label><label class="field">Circuit family<input name="family" value="${esc(meta.family)}" placeholder="e.g. opamp, comparator"></label><label class="field">Topology<input name="topology" value="${esc(meta.topology)}" placeholder="e.g. folded cascode"></label><label class="field">Stage count<input name="stage_count" type="number" min="1" max="20" value="${meta.stage_count||''}" placeholder="Unknown"></label><label class="field">Input mode<select name="input_mode"><option value="">Unknown</option>${['differential','single_ended','other'].map(x=>`<option value="${x}" ${meta.input_mode===x?'selected':''}>${x.replaceAll('_',' ')}</option>`).join('')}</select></label><label class="field">Output mode<select name="output_mode"><option value="">Unknown</option>${['differential','single_ended','other'].map(x=>`<option value="${x}" ${meta.output_mode===x?'selected':''}>${x.replaceAll('_',' ')}</option>`).join('')}</select></label><label class="field">Tags<input name="tags" value="${esc((meta.tags||[]).join(', '))}" placeholder="Comma-separated tags"></label><label class="field wide">Research notes<textarea name="notes" maxlength="10000" placeholder="Evidence, assumptions or observations…">${esc(meta.notes)}</textarea></label></div>`;}
function readMetadata(form){const data=new FormData(form);return {title:data.get('title')||'',description:data.get('description')||'',family:data.get('family')||'',topology:data.get('topology')||'',stage_count:data.get('stage_count')?Number(data.get('stage_count')):null,input_mode:data.get('input_mode')||'',output_mode:data.get('output_mode')||'',tags:String(data.get('tags')||'').split(',').map(x=>x.trim()).filter(Boolean),notes:data.get('notes')||''};}
function renderMetadata(c){
  $('#detail-body').innerHTML=`<div class="metadata-layout"><form class="panel form-panel" id="metadata-form"><h3>Researcher annotations</h3><p class="muted">Saved annotations update future searches. Your supplied values are preserved.</p>${metadataFields(c.metadata)}<div id="metadata-message"></div><div class="form-actions"><span class="help" id="edit-state">Revision ${c.revision} · ${c.sync_state==='synced'?'Synced to Neo4j':'Neo4j sync pending'}</span><button type="submit" class="button primary" id="save-metadata">Save changes</button></div></form><aside><section class="panel facts"><h3>Existing source metadata</h3><div class="fact-row"><span>Dataset</span><span>${esc(c.dataset)}</span></div><div class="fact-row"><span>Circuit ID</span><span class="mono">${esc(c.source_id)}</span></div><div class="facts-block"><h3>Source reference</h3><div class="reference-text">${esc(c.reference_text||'No source reference provided.')}</div></div><div class="facts-block"><h3>Provenance</h3><div class="source-list">Parser: ${esc(c.parser.name)} ${esc(c.parser.version)}<br>Schema: 1.0.0<br>Netlist: ${esc(c.source.primary_netlist)}<br>SHA-256: ${esc(c.source.primary_sha256)}</div></div><div class="facts-block"><h3>Parser notes</h3><p>${c.issues.length} recorded ${c.issues.length===1?'note':'notes'}. ${c.issues.some(i=>i.code==='DUPLICATE_SOURCE_INSTANCE')?'Repeated source instance names are preserved with unique internal IDs.':''}</p></div></section><p class="sidebar-note">Family, topology and stage count are user annotations. No LLM enrichment runs in this V1, and no performance specifications are inferred.</p></aside></div>`;
  const form=$('#metadata-form');form.oninput=()=>{dirty=true;$('#edit-state').textContent='Unsaved changes';};
  form.onsubmit=async e=>{e.preventDefault();const button=$('#save-metadata');const metadata=readMetadata(form);const originVersion=routeVersion;const controls=$$('input,textarea,select',form);controls.forEach(x=>x.disabled=true);button.disabled=true;button.textContent='Saving…';$('#metadata-message').innerHTML='';
    try{const result=await api(`/api/circuits/${enc(c.id)}`,{method:'PATCH',body:JSON.stringify({revision:c.revision,metadata})});if(!form.isConnected||originVersion!==routeVersion)return;dirty=false;current=result;c=result;$('#edit-state').textContent=`Revision ${c.revision} · search refresh and graph sync queued`;$('#metadata-message').innerHTML='<div class="success">Saved locally. Search embeddings and Neo4j are updating in the background.</div>';toast('Annotations saved');}
    catch(error){if(form.isConnected&&originVersion===routeVersion)$('#metadata-message').innerHTML=errorHTML(error.message);}finally{controls.forEach(x=>x.disabled=false);button.disabled=false;button.textContent='Save changes';}
  };
}

async function renderQuery(){
  closeViewer();network?.destroy();network=null;
  main.innerHTML=`<section class="intro"><div><div class="eyebrow">The query workbench</div><h1>Follow the connections.</h1><p>Ask a precise structural question, or retrieve candidates by meaning and topology.</p></div><span class="pill olive">READ-ONLY CYPHER</span></section><div class="query-layout"><div><section class="panel query-panel"><div class="mode-tabs"><button class="button ${queryState.mode==='cypher'?'selected':''}" id="mode-cypher">Cypher</button><button class="button ${queryState.mode==='similarity'?'selected':''}" id="mode-similarity">Similarity search</button></div><div id="query-form"></div></section><div id="query-result" class="query-result"></div></div><aside class="query-aside"><section class="panel facts"><h3 id="aside-title">Start with a question</h3><div id="query-examples"></div><div class="facts-block"><h3>Graph schema</h3><pre class="schema-block">(Circuit)─HAS_DEVICE→(Device)\n         ├HAS_NET───→(Net)\n         └HAS_PORT──→(Port)\n\n(Device)─CONNECTED_TO→(Net)\n  terminal, terminal_ordinal\n\n(Port)───MAPS_TO────→(Net)</pre><p class="help">Use c.id, d.canonical_type, d.source_instance and n.name. Annotations live on Circuit properties. Return nodes or paths to see a graph.</p></div><div class="facts-block"><h3>Recent runs</h3><div id="query-history"><span class="help">No queries yet.</span></div></div></section></aside></div>`;
  for(const mode of ['cypher','similarity'])$(`#mode-${mode}`).onclick=()=>{saveDraft();queryState.mode=mode;persistQuery();lastResult=null;renderQuery();};
  if(queryState.mode==='cypher')renderCypherForm();else renderSimilarityForm();
  renderExamples();refreshHistory();if(lastResult)renderResult(lastResult);
}
function saveDraft(){if($('#cypher-editor')){queryState.query=$('#cypher-editor').value;queryState.parameters=$('#query-parameters').value;}if($('#similarity-text')){queryState.text=$('#similarity-text').value;queryState.reference=referenceId($('#reference-circuit').value);}persistQuery();}
function renderCypherForm(){
  $('#query-form').innerHTML=`<label for="cypher-editor">Cypher statement</label><textarea class="query-editor" id="cypher-editor" spellcheck="false" aria-label="Cypher query">${esc(queryState.query)}</textarea><details class="query-options" ${queryState.parameters!=='{}'?'open':''}><summary>Query parameters · JSON</summary><textarea id="query-parameters" aria-label="Query parameters JSON" spellcheck="false">${esc(queryState.parameters)}</textarea></details><div id="query-error"></div><div class="query-actions"><span class="help">⌘ Enter to run · 10 second timeout<br>First 200 rows displayed</span><button class="button primary" id="run-query">Run query →</button></div>`;
  $('#cypher-editor').oninput=saveDraft;$('#query-parameters').oninput=saveDraft;$('#cypher-editor').onkeydown=e=>{if(e.key==='Tab'){e.preventDefault();const start=e.target.selectionStart;e.target.setRangeText('  ',start,e.target.selectionEnd,'end');saveDraft();}if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();runQuery();}};$('#run-query').onclick=runQuery;
}
function renderSimilarityForm(){
  $('#query-form').innerHTML=`<div class="similarity-form"><label for="similarity-text">Describe the circuits you want to find</label><textarea id="similarity-text" placeholder="e.g. a low-power dynamic comparator with a double-tail structure…">${esc(queryState.text)}</textarea><div class="similarity-options"><div class="reference-picker"><label for="reference-circuit">Reference circuit <span class="muted">· optional</span></label><input id="reference-circuit" autocomplete="off" placeholder="Enter an ID, e.g. 1004" value="${esc(queryState.reference)}"><div id="reference-suggestions" class="suggestions hidden"></div></div><div><label for="search-limit">Results</label><select id="search-limit" style="width:100%"><option>20</option><option>10</option><option>50</option></select></div></div><div class="info-strip">Text retrieves by existing source context and annotations. A reference circuit adds topology comparison. Leave the text blank to compare topology alone.</div><div id="query-error"></div><div class="query-actions"><span class="help">Similarity is a ranking signal.<br>Inspect the netlist to verify each match.</span><button class="button primary" id="run-query">Retrieve circuits →</button></div></div>`;
  $('#similarity-text').oninput=saveDraft;$('#similarity-text').onkeydown=e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();runQuery();}};
  let timer;$('#reference-circuit').oninput=e=>{saveDraft();clearTimeout(timer);timer=setTimeout(async()=>{const search=e.target.value.trim();if(!search){$('#reference-suggestions').classList.add('hidden');return;}try{const data=await api('/api/circuits?'+new URLSearchParams({search,limit:6}));const box=$('#reference-suggestions');if(!box||document.activeElement!==e.target||e.target.value.trim()!==search)return;box.innerHTML=data.items.map(c=>`<button data-reference="${esc(c.id)}">${esc(c.title)} <span class="muted mono">${esc(c.id)}</span></button>`).join('');box.classList.toggle('hidden',!data.items.length);$$('[data-reference]').forEach(b=>b.onclick=()=>{$('#reference-circuit').value=b.dataset.reference;box.classList.add('hidden');saveDraft();});}catch{}},180);};
  $('#reference-circuit').onblur=()=>setTimeout(()=>$('#reference-suggestions')?.classList.add('hidden'),180);$('#run-query').onclick=runQuery;
}
function renderExamples(){
  if(queryState.mode==='cypher'){$('#query-examples').innerHTML=examples.map((x,i)=>`<button class="example" data-example="${i}">${esc(x.name)}<span>${esc(x.note)}</span></button>`).join('');$$('[data-example]').forEach(b=>b.onclick=()=>{queryState.query=examples[Number(b.dataset.example)].query;queryState.parameters='{}';persistQuery();renderCypherForm();});}
  else{$('#query-examples').innerHTML=[['Low-power dynamic comparator','Retrieve by citation and description'],['Bandgap voltage reference','Search source semantics'],['Similar to circuit 1004','Compare the terminal-aware graph']].map((x,i)=>`<button class="example" data-search-example="${i}">${x[0]}<span>${x[1]}</span></button>`).join('');$$('[data-search-example]').forEach(b=>b.onclick=()=>{const i=Number(b.dataset.searchExample);queryState.text=i===0?'Low-power dynamic double-tail comparator':i===1?'Bandgap voltage reference':'';queryState.reference=i===2?'analoggenie:1004':'';persistQuery();renderSimilarityForm();});}
}
async function runQuery(){
  saveDraft();$('#query-error').innerHTML='';$('#reference-suggestions')?.classList.add('hidden');const button=$('#run-query');if(button.disabled)return;button.disabled=true;button.innerHTML='<span class="spinner"></span> Running…';const mode=queryState.mode;
  try{let data;if(mode==='cypher'){let parameters;try{parameters=JSON.parse(queryState.parameters);}catch{throw new Error('Parameters must be valid JSON, e.g. {"id":"analoggenie:1004"}.');}if(!parameters||Array.isArray(parameters)||typeof parameters!=='object')throw new Error('Parameters must be a JSON object.');data=await api('/api/query',{method:'POST',body:JSON.stringify({query:queryState.query,parameters})});}else{data=await api('/api/search',{method:'POST',body:JSON.stringify({text:queryState.text,reference_id:queryState.reference,limit:Number($('#search-limit').value)})});}lastResult={mode,data};if($('#query-result')){renderResult(lastResult);refreshHistory();}}
  catch(e){if($('#query-error'))$('#query-error').innerHTML=errorHTML(e.message);}finally{if(button.isConnected){button.disabled=false;button.textContent=mode==='cypher'?'Run query →':'Retrieve circuits →';}}
}
function cell(value){if(typeof value==='string'&&/^(analoggenie:\d+|uploaded:[\w-]+)$/.test(value))return `<a href="${circuitURL(value)}">${esc(value)} ↗</a>`;if(value&&typeof value==='object'){const label=value.source_instance||value.name||value.type||(Array.isArray(value)?`${value.length} items`:'Object');return `<details><summary>${esc(label)}${value.canonical_type?' · '+esc(value.canonical_type):''}</summary><pre>${esc(JSON.stringify(value,null,2))}</pre></details>`;}return esc(value===null?'null':value);}
function renderResult(result){
  const {mode,data}=result;if(!$('#query-result'))return;
  // Restore an expanded old panel before its position marker is replaced.
  closeViewer();network?.destroy();network=null;
  if(mode==='similarity'){
    $('#query-result').innerHTML=`<div class="result-heading"><h2>${data.items.length} candidates</h2><span class="muted">${data.mode} retrieval · ${fmt(data.total)} compared</span></div><div class="panel">${data.items.length?data.items.map((c,i)=>`<article class="search-card" data-result-id="${esc(c.id)}" tabindex="0" aria-label="Inspect ${esc(c.title)}"><div class="rank">${String(i+1).padStart(2,'0')}</div><div><h3>${esc(c.title)} <span class="muted mono" style="font-size:10px;margin-left:8px">${esc(c.id)}</span></h3><p>${esc(c.description||c.evidence.join(' · '))}</p><div class="type-profile">${profile(c.statistics)}</div></div><div class="scores">${c.semantic_score!==null?`<div>${c.semantic_score.toFixed(3)}<span>SEMANTIC COSINE</span></div>`:''}${c.structural_score!=null?`<div>${c.structural_score.toFixed(3)}<span>FULL-PATTERN SCORE</span></div>`:''}${c.topology_score!==null?`<div>${c.topology_score.toFixed(3)}<span>TOPOLOGY COSINE</span></div>`:''}</div></article>`).join(''):empty('No candidates','Change the description or reference circuit.')}</div><p class="result-note">${esc(data.warning)}${data.reranked?` Top ${data.reranked} topology candidates rescored using full structural patterns.`:''}${data.mode==='hybrid'?' Results combine independent ranks using reciprocal rank fusion.':''}</p><details class="query-options"><summary>Structured search request · JSON</summary><pre class="schema-block">${esc(JSON.stringify(data.request,null,2))}</pre></details>`;
    $$('[data-result-id]').forEach(x=>{x.onclick=()=>openCircuit(x.dataset.resultId);x.onkeydown=e=>{if(e.key==='Enter')openCircuit(x.dataset.resultId);};});
  }else{
    $('#query-result').innerHTML=`<div class="result-heading"><h2>${data.rows.length} ${data.rows.length===1?'row':'rows'} returned</h2><div class="results-controls"><span class="muted">${data.elapsed_ms} ms</span><button class="button small" id="export-results">Export JSON ↗</button></div></div>${data.circuits.length?`<div class="result-circuits">${data.circuits.map(c=>`<button class="button small" data-result-id="${esc(c.id)}">${esc(c.title)} ↗</button>`).join('')}</div>`:''}<div class="panel"><div class="panel-heading"><h3>Query results</h3><div class="segmented"><button id="result-table-tab" class="active">Table</button><button id="result-graph-tab" ${!data.graph.nodes.length?'disabled':''}>Graph ${data.graph.nodes.length?'· '+data.graph.nodes.length:''}</button></div></div><div id="result-content"></div></div><p class="result-note">${data.truncated?`Results capped at ${data.limit} rows. Add a LIMIT or narrow the query.`:!data.graph.nodes.length?'Return devices, nets, relationships or paths to enable the graph view.':'Graph view contains the nodes and relationships returned by this query.'}</p>`;
    const table=()=>{$('#result-table-tab').classList.add('active');$('#result-graph-tab').classList.remove('active');$('#result-content').innerHTML=data.rows.length?`<div class="table-wrap"><table class="results-table"><thead><tr>${data.columns.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${data.rows.map(r=>`<tr>${data.columns.map(c=>`<td>${cell(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:empty('No matches for this pattern','Try a less restrictive query or inspect an example circuit.');};
    table();$('#result-table-tab').onclick=()=>{network?.destroy();network=null;table();};$('#result-graph-tab').onclick=()=>{$('#result-table-tab').classList.remove('active');$('#result-graph-tab').classList.add('active');$('#result-content').innerHTML=`<section class="panel query-graph-panel"><div class="panel-heading viewer-heading"><h3>Returned connectivity</h3>${expandButton(null)}</div><div class="graph-wrap"><div class="graph-tools">${graphTools()}</div><div id="result-graph" class="graph-canvas"></div></div></section>`;const panel=$('.query-graph-panel');bindExpansion(panel);drawGraph($('#result-graph'),data.graph,true);};
    $('#export-results').onclick=()=>exportJSON(data,'query-results.json');$$('[data-result-id]').forEach(b=>b.onclick=()=>openCircuit(b.dataset.resultId));
    if(data.graph.truncated)$('#query-result .result-note').textContent+=' Graph display capped at 1,200 nodes / 3,000 relationships; narrow the query to inspect the complete result.';
  }
}
async function refreshHistory(){try{const history=await api('/api/history');if(!$('#query-history'))return;$('#query-history').innerHTML=history.length?history.slice(0,6).map((h,i)=>`<button class="history-item" data-history="${i}" title="${esc(h.query)}">${esc(h.kind==='cypher'?h.query.split('\n')[0]:h.query)}</button>`).join(''):'<span class="help">Your successful runs appear here.</span>';$$('[data-history]').forEach(b=>b.onclick=()=>{const h=history[Number(b.dataset.history)];if(h.kind==='cypher'){queryState.mode='cypher';queryState.query=h.query;queryState.parameters=h.parameters;}else{const p=JSON.parse(h.parameters);queryState.mode='similarity';queryState.text=p.text;queryState.reference=p.reference_id;}lastResult=null;persistQuery();renderQuery();});}catch{}}

let uploadImage='',validatedUpload='';
function openUpload(){
  uploadImage='';validatedUpload='';
  $('#upload-content').innerHTML=`<div class="dialog-header"><div><div class="eyebrow">Grow the collection</div><h2>Add a circuit.</h2><p>A valid netlist and a short description are all you need.</p></div><button class="button icon" id="close-upload" aria-label="Close upload">×</button></div><form class="dialog-body" id="upload-form"><label class="field">Display title <span class="help">Optional</span><input name="title" placeholder="e.g. resistively loaded common-source amplifier"></label><div class="upload-file"><span>Load a .cir, .sp or .txt netlist</span><input id="netlist-file" type="file" accept=".cir,.sp,.spice,.txt" aria-label="Netlist file"></div><label class="field">Netlist <span class="help">Required · flat SPICE or parenthesized typed devices</span><textarea class="upload-editor" id="upload-netlist" required spellcheck="false" placeholder="M1 (out in VSS VSS) nmos4 w=10u l=1u\nR1 (VDD out) resistor r=10k"></textarea></label><div style="margin-top:17px" class="form-grid"><label class="field wide">Basic description <span class="help">Required</span><textarea name="description" required placeholder="What does this circuit do? What is known about it?"></textarea></label><label class="field wide">External ports <span class="help">Optional · exact net names separated by spaces</span><input id="upload-ports" placeholder="VDD VSS in out"></label></div><details class="query-options"><summary>Optional annotations and schematic</summary><div class="form-grid" style="margin-top:17px"><label class="field">Circuit family<input name="family" placeholder="e.g. amplifier"></label><label class="field">Topology<input name="topology" placeholder="e.g. common source"></label><label class="field">Stage count<input name="stage_count" type="number" min="1" max="20" placeholder="Unknown"></label><label class="field">Tags<input name="tags" placeholder="Comma-separated"></label><label class="field">Input mode<select name="input_mode"><option value="">Unknown</option><option value="single_ended">Single ended</option><option value="differential">Differential</option></select></label><label class="field">Output mode<select name="output_mode"><option value="">Unknown</option><option value="single_ended">Single ended</option><option value="differential">Differential</option></select></label><label class="field wide">Research notes<textarea name="notes"></textarea></label><div class="field wide">Schematic image <span class="help">PNG/JPEG · up to 6 MB</span><input id="schematic-file" type="file" accept="image/png,image/jpeg" aria-label="Schematic file"></div></div></details><div id="upload-error"></div><div id="upload-preview" class="upload-preview"></div><div class="form-actions"><span class="help">Uploads are parsed locally.<br>Your annotations remain yours.</span><div style="display:flex;gap:8px"><button type="button" class="button" id="validate-upload">Validate netlist</button><button type="submit" class="button primary" id="save-upload" disabled>Add to library →</button></div></div></form>`;
  const form=$('#upload-form');$('#close-upload').onclick=()=>$('#upload-dialog').close();
  form.oninput=()=>{validatedUpload='';$('#save-upload').disabled=true;$('#upload-preview').innerHTML='';};
  $('#netlist-file').onchange=async e=>{const file=e.target.files[0];if(!file)return;if(file.size>1_000_000){$('#upload-error').innerHTML=errorHTML('Netlist files must be under 1 MB.');return;}$('#upload-netlist').value=await file.text();validatedUpload='';$('#save-upload').disabled=true;$('#upload-preview').innerHTML='';};
  $('#schematic-file').onchange=async e=>{const file=e.target.files[0];uploadImage='';if(!file)return;if(file.size>6_000_000){$('#upload-error').innerHTML=errorHTML('Choose a schematic smaller than 6 MB.');e.target.value='';return;}uploadImage=await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsDataURL(file);});};
  const payload=()=>{const metadata=readMetadata(form);return {netlist:$('#upload-netlist').value,description:metadata.description,ports:$('#upload-ports').value,metadata,image_base64:uploadImage};};
  $('#validate-upload').onclick=async()=>{const b=$('#validate-upload');b.disabled=true;$('#upload-error').innerHTML='';try{if(!form.reportValidity())return;const data=await api('/api/uploads/preview',{method:'POST',body:JSON.stringify(payload())});validatedUpload=JSON.stringify(payload());$('#upload-preview').innerHTML=`<div class="success">Netlist validated.<div class="preview-stats"><span><strong>${data.statistics.device_count}</strong> devices</span><span><strong>${data.statistics.net_count}</strong> nets</span><span><strong>${data.statistics.connection_count}</strong> terminal connections</span><span><strong>${data.ports.length}</strong> ports</span></div></div>${data.warnings.map(x=>`<p class="help" style="margin-top:10px">${esc(x)}</p>`).join('')}`;$('#save-upload').disabled=false;}catch(e){$('#upload-error').innerHTML=errorHTML(e.message);}finally{b.disabled=false;}};
  form.onsubmit=async e=>{e.preventDefault();if(!validatedUpload||validatedUpload!==JSON.stringify(payload())){$('#upload-error').innerHTML=errorHTML('Validate the current netlist before adding it.');return;}const b=$('#save-upload');b.disabled=true;b.textContent='Adding…';try{const result=await api('/api/uploads',{method:'POST',body:JSON.stringify(payload())});$('#upload-dialog').close();toast('Circuit added · search and graph sync queued');updateStatus();openCircuit(result.id);}catch(error){$('#upload-error').innerHTML=errorHTML(error.message);b.disabled=false;b.textContent='Add to library →';}};
  $('#upload-dialog').showModal();
}
$('#open-upload').onclick=openUpload;

async function route(){
  if(restoringHash){restoringHash=false;return;}
  if(dirty){if(!confirm('You have unsaved annotations. Discard them and leave this circuit?')){restoringHash=true;location.hash=lastHash;return;}dirty=false;}
  closeViewer();saveDraft();lastHash=location.hash;const version=++routeVersion;++libraryVersion;++graphVersion;network?.destroy();network=null;graphData=null;
  const parts=location.hash.replace(/^#/,'').split('/');const page=parts[0]||'library';$('#nav-library').classList.toggle('active',page!=='query');$('#nav-query').classList.toggle('active',page==='query');
  main.classList.toggle('inspector-page',page==='circuit');
  document.body.classList.toggle('details-page',page==='circuit');
  if(page==='circuit')await renderDetail(decodeURIComponent(parts[1]||''),['graph','schematic','netlist','metadata'].includes(parts[2])?parts[2]:'graph',version);else if(page==='query')await renderQuery();else await renderLibrary();
  window.scrollTo(0,0);
}
window.addEventListener('hashchange',route);window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
document.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)&&$('#library-search')){e.preventDefault();$('#library-search').focus();}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!expandedViewer&&$('#detail-body')?.classList.contains('show-details')){setDetailsVisible(false);$('#toggle-details')?.focus();}});
document.addEventListener('click',e=>{if(!e.target.closest('.reference-picker'))$('#reference-suggestions')?.classList.add('hidden');});
updateStatus();route();setInterval(updateStatus,5000);
