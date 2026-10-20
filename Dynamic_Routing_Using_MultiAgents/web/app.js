/* Step 9 UI: accessible network editing, motion and real Python agent integration. */
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const SVG_NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, text) => {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (text !== undefined) node.textContent = text;
  return node;
};
const pad = n => String(n).padStart(2, '0');
let state = null, selection = null, connecting = false, linkFrom = null;
let drag = null, addPoint = null, running = false, cancelRun = false;
let noticeTimer = 0;

async function getState() {
  const res = await fetch('/api/state', {cache: 'no-store'});
  if (!res.ok) throw new Error('Unable to connect to the local server');
  return res.json();
}
async function action(payload, quiet = false) {
  const res = await fetch('/api/action', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const answer = await res.json();
  if (!res.ok) throw new Error(answer.error || 'Something went wrong');
  state = answer.state;
  if (answer.notice && !quiet) toast(answer.notice);
  render();
  return answer;
}
async function safeAction(payload, quiet = false) {
  try { return await action(payload, quiet); }
  catch (err) { toast(err.message, true); return null; }
}
function toast(message, error = false) {
  const node = $('toast');
  node.textContent = message;
  node.classList.toggle('error', error);
  node.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => node.hidden = true, 4000);
}
function devices() { return state?.devices || []; }
function links() { return state?.links || []; }
function device(name) { return devices().find(d => d.name === name); }
function linkKey(link) { return [link.a, link.b].sort().join('::'); }
function coords(event) {
  const svg = $('network-svg');
  const p = svg.createSVGPoint(); p.x = event.clientX; p.y = event.clientY;
  return p.matrixTransform(svg.getScreenCTM().inverse());
}
function setSelectOptions(select, nodes, preferred) {
  const old = select.value || preferred;
  select.replaceChildren(...nodes.map(d => new Option(d.name, d.name)));
  if (nodes.some(d => d.name === old)) select.value = old;
  else if (nodes.some(d => d.name === preferred)) select.value = preferred;
}
function render() {
  if (!state) return;
  const s = state.stats;
  $('metric-devices').textContent = devices().length;
  $('metric-delivered').textContent = s.delivered.toLocaleString();
  $('metric-pdr').textContent = s.attempted ? (s.delivered / s.attempted * 100).toFixed(1) + '%' : '—';
  $('metric-queued').textContent = s.in_flight.toLocaleString();
  $('metric-dropped-note').textContent = s.dropped + ' packets dropped';
  $('canvas-device-count').textContent = devices().length + ' devices';
  $('canvas-link-count').textContent = links().length + ' connections';
  $('empty-network').hidden = devices().length !== 0;
  $('route-mode').value = state.mode;
  $('health-trusted').textContent = Object.keys(state.trust).length - state.untrusted.length + ' / ' + Object.keys(state.trust).length;
  $('health-busy').textContent = state.busy.length;
  $('health-q').textContent = state.q_entries;
  let status = $('health-message');
  const bad = state.untrusted.length;
  status.className = 'health-note' + (bad ? ' danger' : state.busy.length ? ' warning' : '');
  status.textContent = bad ? `⚠ ${bad} untrusted: ${state.untrusted.join(', ')}` :
    state.busy.length ? `△ Congestion detected: ${state.busy.join(', ')}` : '✓ Agents operating normally';
  setSelectOptions($('source-select'), devices(), 'PC1');
  updateManageControls();
  setSelectOptions($('target-select'), devices(), 'S1');
  renderScenarioControls();
  drawGraph(); drawChart(); renderActivity(); renderInspector(); renderSelection(); renderRouteFeedback();
}


function updateManageControls() {
  const devPicker = $('manage-device');
  const oldDev = devPicker.value || (selection?.type === 'node' ? selection.name : '');
  devPicker.replaceChildren(...devices().map(d=>new Option(`${d.name} · ${d.kind}`,d.name)));
  if (devices().some(d=>d.name===oldDev)) devPicker.value = oldDev;
  const oldLink = $('manage-link').value || (selection?.type==='link'?selection.key:'');
  const picker = $('manage-link');
  picker.replaceChildren(...links().map(l=>new Option(`${l.a} ↔ ${l.b}`,linkKey(l))));
  if (links().some(l=>linkKey(l)===oldLink))picker.value=oldLink;
  $('delete-device').disabled = !devPicker.value;
  $('delete-link').disabled = !picker.value;
}
function renderSelection() {
  const hud = $('selection-hud');
  let name = selection?.type==='node'&&device(selection.name)?selection.name:
    selection?.type==='link'&&links().some(l=>linkKey(l)===selection.key)?selection.key.replace('::',' ↔ '):'';
  hud.hidden = !name;
  $('selected-label').textContent = name?`Selected: ${name}`:'';
  if (selection?.type==='node' && device(selection.name)) $('manage-device').value=selection.name;
  if (selection?.type==='link' && links().some(l=>linkKey(l)===selection.key)) $('manage-link').value=selection.key;
}
function forwardingHint(source, target) {
  // Explain an endpoint transit restriction only when a physical path actually goes through one.
  const queue = [[source]], visited = new Set([source]);
  let connectedPath = null;
  while (queue.length) {
    const path = queue.shift(), current = path[path.length-1];
    if (current === target) { connectedPath = path; break; }
    for (const link of links()) {
      if (!link.enabled) continue;
      const next = link.a===current?link.b:link.b===current?link.a:null;
      if (next && !visited.has(next) && device(next)?.online) {
        queue.push([...path,next]);visited.add(next);
      }
    }
  }
  const blocking = connectedPath?.slice(1,-1).find(n=>['PC','SERVER'].includes(device(n)?.kind));
  const hint = blocking ? ` ${blocking} is an end device and cannot forward transit packets. Connect through a switch or router instead.`
    : ' Check that both devices are online, connections are active, and a usable route exists.';
  return `No valid route from ${source} to ${target}.${hint}`;
}
function renderRouteFeedback() {
  const output = $('route-feedback');
  const latest = state.latest || {};
  const from=$('source-select').value, to=$('target-select').value;
  const path = latest.route;
  if (latest.type==='preview') {
    const isValid = Array.isArray(path)&&path.length>0;
    output.className = 'route-feedback'+(isValid?' ok':' error');
    output.textContent = isValid ? `Route ready: ${path.join(' → ')}` : forwardingHint(from,to);
  } else if (latest.type==='traffic') {
    output.className = 'route-feedback'+(Array.isArray(path)&&path.length?' ok':' error');
    output.textContent = Array.isArray(path)&&path.length ? `Sending along ${path.join(' → ')} · Step ${latest.step}` : forwardingHint(from,to);
  } else if (latest.type==='compare') {
    output.className='route-feedback';
    output.textContent=`Comparison: Dijkstra ${latest.dijkstra?.join(' → ')||'no path'} · Q-Learning ${latest.qlearning?.join(' → ')||'no path'}`;
  } else {
    output.className='route-feedback';
    output.textContent='Select endpoints in Simulation Controls, then click Preview route.';
  }
}
async function deleteDevice(name) {
  if (!name || !device(name))return;
  if (!confirm(`Delete ${name} and all its connections? This will reset the current simulation.`))return;
  const response = await safeAction({op:'remove_device',name});
  if (response){selection=null;render();toast(`${name} removed from the network`);}
}
async function deleteLink(key) {
  const l=links().find(x=>linkKey(x)===key);
  if (!l)return;
  if (!confirm(`Delete connection ${l.a} ↔ ${l.b}?`))return;
  const response = await safeAction({op:'remove_link',a:l.a,b:l.b});
  if (response){selection=null;render();toast(`Connection ${l.a} ↔ ${l.b} removed`);}
}

function renderScenarioControls() {
  const candidates = devices().filter(d => d.kind === 'ROUTER' || d.kind === 'SWITCH');
  setSelectOptions($('attack-device'), candidates, 'R2');
  setSelectOptions($('congestion-device'), candidates, 'R2');
  const attack = $('attack-device').value;
  const mode = state.behaviors[attack] || 'normal';
  // Preserve an unsaved selection until another device is chosen, but reflect live backend changes.
  if (!$('attack-mode').dataset.userEdited || $('attack-mode').dataset.selectedDevice !== attack) {
    $('attack-mode').value = mode;
    $('attack-mode').dataset.userEdited = '';
  }
  $('attack-mode').dataset.selectedDevice = attack;
  $('attack-apply').disabled = !attack;
  $('attack-restore').disabled = !attack;
  const score = state.trust[attack];
  $('attack-status').textContent = attack ? `${attack}: ${mode.toUpperCase()} · Trust ${score == null ? 'N/A' : Math.round(score*100)+'%'}${state.untrusted.includes(attack) ? ' · UNTRUSTED' : ''}` : 'Add a router or switch to start.';
  const target = $('congestion-device').value;
  $('congestion-apply').disabled = !target;
  $('congestion-restore').disabled = !state.overloads.includes(target);
  const q = target ? state.stats.queues[target] || 0 : 0;
  const limit = device(target)?.queue_limit || 1;
  $('congestion-status').textContent = target ? `${target}: queue ${q}/${limit} · ${state.busy.includes(target) ? 'CONGESTED' : 'No congestion flag'}${state.overloads.includes(target) ? ' · stress limits active' : ''}` : 'Add a router or switch to start.';
  $('congestion-enabled').checked = state.congestion_settings.enabled;
  $('congestion-threshold').value = Math.round(state.congestion_settings.threshold * 100);
  $('congestion-threshold-label').textContent = Math.round(state.congestion_settings.threshold * 100) + '%';
}

function addSvg(parent, tag, attrs, text) { const child = el(tag, attrs, text); parent.appendChild(child); return child; }
function drawGraph() {
  const svg = $('network-svg');
  svg.querySelector('#graph-layer')?.remove();
  const layer = addSvg(svg, 'g', {id: 'graph-layer'});
  const route = state.latest.route || [];
  const routePairs = new Set(route.slice(1).map((node, i) => [node, route[i]].sort().join('::')));
  for (const [index, link] of links().entries()) {
    const a = device(link.a), b = device(link.b);
    if (!a || !b) continue;
    const k = linkKey(link);
    const selected = selection?.type === 'link' && selection.key === k;
    const active = routePairs.has(k) && link.enabled;
    const lineAttrs = {x1:a.x,y1:a.y,x2:b.x,y2:b.y};
    addSvg(layer, 'line', {...lineAttrs, 'stroke':'transparent','stroke-width':32,
      'data-link-index':index, 'cursor':'pointer'});
    addSvg(layer,'line',{...lineAttrs,class:'network-link' + (active?' is-route':'') + (selected?' is-selected':'') + (!link.enabled?' disabled':''),
      'data-link-index':index,'pointer-events':'none'});
    const mx = (a.x+b.x)/2, my=(a.y+b.y)/2;
    addSvg(layer,'text',{x:mx,y:my-10,class:'link-weight','pointer-events':'none'},`${link.delay}ms`);
    if (active && state.latest.type === 'traffic') {
      const ball = addSvg(layer, 'circle', {r:6,class:'packet-dot','pointer-events':'none'});
      const animation = addSvg(ball,'animateMotion',{dur:'1.65s',repeatCount:'indefinite',
        path:`M ${a.x} ${a.y} L ${b.x} ${b.y}`});
    }
  }
  for (const d of devices()) {
    const selected = selection?.type === 'node' && selection.name === d.name;
    const bad = state.untrusted.includes(d.name);
    const utilization = (state.stats.queues[d.name] || 0) / d.queue_limit;
    const g = addSvg(layer,'g',{'data-kind':d.kind,'data-node':d.name,transform:`translate(${d.x} ${d.y})`,
      class:'network-node' + (bad?' untrusted':'') + (selected?' selected':'') + (!d.online?' is-offline':'')});
    addSvg(g,'circle',{r:43,class:'main-circle'});
    addSvg(g,'circle',{r:51,fill:'transparent'});
    addSvg(g,'text',{x:0,y:11,class:'node-glyph','pointer-events':'none'},({PC:'▣',ROUTER:'⬡',SWITCH:'⌘',SERVER:'▤'})[d.kind]);
    addSvg(g,'text',{x:0,y:68,class:'node-label','pointer-events':'none'},d.name.length > 20 ? d.name.slice(0,17) + '…' : d.name);
    addSvg(g,'text',{x:0,y:84,class:'node-sub','pointer-events':'none'},d.kind + (!d.online?' • OFFLINE':''));
    addSvg(g,'rect',{x:-30,y:96,width:60,height:5,rx:2,class:'node-queue-bg','pointer-events':'none'});
    if (utilization) addSvg(g,'rect',{x:-30,y:96,width:60*Math.min(1,utilization),height:5,rx:2,
      class:'node-queue-progress' + (utilization>=0.6?' high':''),'pointer-events':'none'});
    if (bad) {addSvg(g,'circle',{cx:37,cy:-34,r:11,class:'node-trust-badge','pointer-events':'none'});
      addSvg(g,'text',{x:37,y:-29,fill:'white','text-anchor':'middle','font-size':12,'font-weight':800,'pointer-events':'none'},'!');}
    if (state.busy.includes(d.name) && !bad) {
      addSvg(g,'circle',{cx:37,cy:-34,r:9,fill:'#e2a256','pointer-events':'none'});
    }
  }
}
function drawChart() {
  const svg = $('trend-chart'); svg.replaceChildren();
  const timeline = state.timeline;
  const points = [{time:0,delivered:0,dropped:0,queued:0},...timeline.slice(-40)];
  const max = Math.max(10,...points.flatMap(p=>[p.delivered,p.dropped,p.queued]));
  const chart = {x:16,y:11,w:560,h:105};
  for (let i=0;i<=3;i++) {
    const y = chart.y+chart.h*i/3;
    addSvg(svg,'line',{x1:chart.x,y1:y,x2:chart.x+chart.w,y2:y,stroke:'#d9e7f0','stroke-dasharray':'3 5'});
    addSvg(svg,'text',{x:chart.x+chart.w+5,y:y+3,fill:'#6e899d','font-size':9},Math.round(max*(1-i/3)));
  }
  for(const [key,color] of [['delivered','#079c76'],['dropped','#d84c59'],['queued','#d69a37']]) {
    const line = points.map((p,i)=>`${chart.x+chart.w*i/Math.max(1,points.length-1)},${chart.y+chart.h-chart.h*(p[key]/max)}`).join(' ');
    addSvg(svg,'polyline',{points:line,fill:'none',stroke:color,'stroke-width':2.5,'stroke-linecap':'round','stroke-linejoin':'round'});
  }
}
function renderActivity() {
  const log = $('activity-list');
  const activity = state.activity.slice(-9).reverse();
  log.innerHTML = activity.length ? activity.map(message => {
    const delegation = message.startsWith('Main Agent');
    const cut = message.length > 135 ? message.slice(0,135) + '…' : message;
    return `<div class="activity-entry"><span class="activity-icon">${delegation?'↗':'↙'}</span><div>${esc(cut)}</div></div>`;
  }).join('') : '<div class="muted-empty">Start a simulation to see the Main Agent delegate tasks and receive results.</div>';
}
function renderInspector() {
  const box = $('inspector-selected');
  if (selection?.type === 'node' && device(selection.name)) {
    const d = device(selection.name), score = state.trust[d.name];
    const behavior = state.behaviors[d.name] || 'normal';
    box.innerHTML = `<div class="inspector-name">${esc(d.name)}</div><div class="inspector-kind">${esc(d.kind)} · TRUST ${score == null ? 'N/A' : Math.round(score*100)+'%'}</div>
      <label class="inspect-toggle">Device online <input id="inspect-online" type="checkbox" ${d.online?'checked':''}></label>
      <div class="two-col"><label>Processing capacity<input id="inspect-cap" type="number" min="1" value="${d.capacity}"></label><label>Queue limit<input id="inspect-queue" type="number" min="1" value="${d.queue_limit}"></label></div>
      <button id="inspect-save" class="btn-outline full-width">Save device settings</button>
      ${(d.kind==='ROUTER'||d.kind==='SWITCH')?`<label class="input-small">Simulated forwarding behavior<select id="inspect-behavior"><option value="normal">Normal</option><option value="blackhole">Blackhole (drops all)</option><option value="grayhole">Grayhole (selective drops)</option></select></label><button id="repair-btn" class="quiet-link">Restore behavior and trust →</button>`:''}
      <div class="inspect-actions"><button id="remove-item" class="danger-text">✕ Remove device</button></div>`;
    $('inspect-online').onchange = e => safeAction({op:'device_status',name:d.name,online:e.target.checked});
    $('inspect-save').onclick = () => safeAction({op:'device_settings',name:d.name,capacity:$('inspect-cap').value,queue_limit:$('inspect-queue').value});
    if ($('inspect-behavior')) {
      $('inspect-behavior').value = behavior;
      $('inspect-behavior').onchange = e => safeAction({op:'behavior',name:d.name,mode:e.target.value});
      $('repair-btn').onclick = () => safeAction({op:'repair',name:d.name});
    }
    $('remove-item').onclick = () => deleteDevice(d.name);
  } else if (selection?.type === 'link' && links().some(l=>linkKey(l)===selection.key)) {
    const l = links().find(l=>linkKey(l)===selection.key);
    box.innerHTML = `<div class="inspector-name">${esc(l.a)} ↔ ${esc(l.b)}</div><div class="inspector-kind">NETWORK CONNECTION</div>
      <label class="inspect-toggle">Connection enabled <input id="inspect-enabled" type="checkbox" ${l.enabled?'checked':''}></label>
      <div class="two-col"><label>Delay (ms)<input id="inspect-delay" type="number" min="0.01" step="0.1" value="${l.delay}"></label><label>Bandwidth (Mbps)<input id="inspect-bandwidth" type="number" min="0.01" step="0.1" value="${l.bandwidth}"></label></div>
      <button id="inspect-save" class="btn-outline full-width">Save link settings</button>
      <button id="remove-item" class="danger-text">✕ Remove connection</button>`;
    $('inspect-enabled').onchange = e => safeAction({op:'link_status',a:l.a,b:l.b,enabled:e.target.checked});
    $('inspect-save').onclick = () => safeAction({op:'link_settings',a:l.a,b:l.b,delay:$('inspect-delay').value,bandwidth:$('inspect-bandwidth').value,enabled:$('inspect-enabled').checked});
    $('remove-item').onclick = () => deleteLink(linkKey(l));
  } else {
    selection = null;
    box.innerHTML = '<div class="selected-placeholder"><span>⌖</span><p>Select a device or connection on the canvas to inspect or configure it.</p></div>';
  }
}
function setConnectMode(active) {
  connecting = active; linkFrom = null;
  $('connect-mode').classList.toggle('is-active',active);
  $('connect-mode').innerHTML = active ? '✕ Cancel connection' : '<span>⌁</span> Create connection';
  $('canvas-hint').hidden = !active;
  $('canvas-hint').textContent = 'Choose the first device to connect';
}
function clickNode(name) {
  if (connecting) {
    if (linkFrom === null) {
      linkFrom = name;
      $('canvas-hint').textContent = `Connecting from ${name} — choose the second device`;
      return;
    }
    if (linkFrom === name) return toast('Select two different devices', true);
    const first = linkFrom; setConnectMode(false);
    selection = {type:'link',key:[first,name].sort().join('::')};
    safeAction({op:'connect',a:first,b:name,delay:2,bandwidth:100});
  } else { selection = {type:'node',name}; render(); }
}
function clickLink(index) {
  if (connecting) return;
  const link = links()[index];
  if (link) {selection = {type:'link',key:linkKey(link)};render();}
}
function onPointerDown(e) {
  const n = e.target.closest('[data-node]');
  const l = e.target.closest('[data-link-index]');
  if (n) {
    const name = n.getAttribute('data-node');
    const p = coords(e), d = device(name);
    drag = {name,sx:p.x,sy:p.y,ox:d.x,oy:d.y,moved:false};
    $('network-svg').setPointerCapture(e.pointerId);
    e.preventDefault();
  } else if (l) {
    clickLink(Number(l.getAttribute('data-link-index')));
  } else if (!connecting) {
    selection=null;render();
  }
}
function onPointerMove(e) {
  if (!drag) return;
  const p = coords(e), dx = p.x-drag.sx, dy = p.y-drag.sy;
  if (Math.abs(dx)+Math.abs(dy)>3) drag.moved=true;
  if (!drag.moved) return;
  const d = device(drag.name);
  d.x = Math.min(860,Math.max(40,drag.ox+dx));
  d.y = Math.min(480,Math.max(40,drag.oy+dy));
  drawGraph();
}
function onPointerUp(e) {
  if (!drag) return;
  const old = drag; drag = null;
  if (!old.moved) clickNode(old.name);
  else {selection = {type:'node',name:old.name};safeAction({op:'move_device',name:old.name,x:device(old.name).x,y:device(old.name).y},true);}
}
function openAdd(kind='ROUTER',p=null) {
  addPoint = p;
  const defaults={PC:[5,10],ROUTER:[20,50],SWITCH:[30,60],SERVER:[25,50]};
  $('add-kind').value=kind;
  const nums = devices().filter(d=>d.kind===kind).length+1;
  const prefix={PC:'PC',ROUTER:'R',SWITCH:'SW',SERVER:'S'}[kind];
  let next=nums;while(device(prefix+next))next++;
  $('add-name').value=prefix+next;
  $('add-capacity').value=defaults[kind][0];
  $('add-queue').value=defaults[kind][1];
  $('modal-overlay').hidden=false;
  $('add-name').focus(); $('add-name').select();
}
function closeAdd() {$('modal-overlay').hidden=true;addPoint=null;}
function delay(ms) {return new Promise(resolve=>setTimeout(resolve,ms));}
function setRunning(value) {
  running=value;
  $('run-btn').textContent=value?'Ⅱ Pause simulation':'▶ Run simulation';
  $('step-btn').disabled=value;
}
async function simulateOne(rate) {
  if (!state) return;
  return safeAction({op:'step',source:$('source-select').value,target:$('target-select').value,rate},true);
}
async function runSimulation() {
  if (running) {cancelRun=true;toast('Stopping after the current step');return;}
  const count=Number($('traffic-steps').value),rate=Number($('traffic-rate').value);
  if (!Number.isInteger(count)||count<1||count>100||!Number.isInteger(rate)||rate<0||rate>200) return toast('Use 1–100 steps and 0–200 packets per step',true);
  if (rate && $('source-select').value===$('target-select').value) return toast('Choose different source and destination',true);
  cancelRun=false;setRunning(true);
  for(let i=0;i<count&&!cancelRun;i++) {
    const result=await simulateOne(rate);
    if (!result) break;
    $('run-btn').textContent=`Ⅱ Pause · ${i+1}/${count}`;
    if(i<count-1) await delay(Number($('tick-speed').value));
  }
  setRunning(false);
}
function bindEvents() {
  $('network-svg').addEventListener('pointerdown',onPointerDown);
  $('network-svg').addEventListener('pointermove',onPointerMove);
  $('network-svg').addEventListener('pointerup',onPointerUp);
  $('network-svg').addEventListener('pointercancel',onPointerUp);
  $('network-svg').addEventListener('dblclick',e=>{
    if (!e.target.closest('[data-node]')) openAdd('ROUTER',coords(e));
  });
  document.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>openAdd(b.dataset.add));
  $('connect-mode').onclick=()=>setConnectMode(!connecting);
  $('manage-device').onchange=()=>{const name=$('manage-device').value;if(name){selection={type:'node',name};render();}};
  $('manage-link').onchange=()=>{const key=$('manage-link').value;if(key){selection={type:'link',key};render();}};
  $('delete-device').onclick=()=>deleteDevice($('manage-device').value);
  $('delete-link').onclick=()=>deleteLink($('manage-link').value);
  $('selection-remove').onclick=()=>{if(selection?.type==='node')deleteDevice(selection.name);else if(selection?.type==='link')deleteLink(selection.key);};

  $('modal-close').onclick=closeAdd;
  $('modal-cancel').onclick=closeAdd;
  $('modal-overlay').addEventListener('click',e=>{if(e.target===$('modal-overlay'))closeAdd();});
  $('add-kind').onchange=e=>{
    const defaults={PC:[5,10],ROUTER:[20,50],SWITCH:[30,60],SERVER:[25,50]};
    $('add-capacity').value=defaults[e.target.value][0];
    $('add-queue').value=defaults[e.target.value][1];
  };
  $('add-form').onsubmit=async e=>{
    e.preventDefault();
    const kind=$('add-kind').value;
    const p=addPoint||{x:180+Math.random()*500,y:110+Math.random()*290};
    const result=await safeAction({op:'add_device',kind,name:$('add-name').value,
      capacity:$('add-capacity').value,queue_limit:$('add-queue').value,x:p.x,y:p.y});
    if(result){closeAdd(); selection={type:'node',name:$('add-name').value};render();}
  };
  $('route-mode').onchange=e=>safeAction({op:'routing_mode',mode:e.target.value});
  for(const name of ['source-select','target-select']){
    $(name).addEventListener('change',()=>{
      if(state){state.latest={};renderRouteFeedback();}
    });
  }
  $('attack-mode').onchange=()=>{$('attack-mode').dataset.userEdited = '1';};
  $('attack-device').onchange=()=>{ $('attack-mode').dataset.userEdited=''; renderScenarioControls(); };
  $('congestion-device').onchange=renderScenarioControls;
  $('attack-apply').onclick=async()=>{
    const name=$('attack-device').value, mode=$('attack-mode').value;
    $('attack-mode').dataset.userEdited='';
    if (await safeAction({op:'behavior', name, mode})) {
      toast(`${name}: ${mode} simulation configured. Run traffic to observe trust changes.`);
    }
  };
  $('attack-restore').onclick=async()=>{
    const name=$('attack-device').value;
    // A brand-new device has no prior trust observation, so normal behavior suffices.
    const action = state.trust[name] == null ? {op:'behavior',name,mode:'normal'} : {op:'repair',name};
    $('attack-mode').dataset.userEdited='';
    if (await safeAction(action)) toast(`${name}: behavior restored and trust reset.`);
  };
  $('congestion-apply').onclick=async()=>{
    const name=$('congestion-device').value;
    const capacity=Number($('overload-capacity').value), queue_limit=Number($('overload-queue').value);
    if (!Number.isInteger(capacity)||capacity<1||!Number.isInteger(queue_limit)||queue_limit<1) return toast('Enter positive whole-number capacity and queue limits.',true);
    if (await safeAction({op:'overload',name,capacity,queue_limit})) toast(`Capacity reduced at ${name}. Select Stress test and run traffic.`);
  };
  $('congestion-restore').onclick=async()=>{
    const name=$('congestion-device').value;
    if(await safeAction({op:'restore_limits',name})) toast(`${name}: original device capacity restored.`);
  };
  $('traffic-light').onclick=()=>{$('traffic-rate').value=1;$('traffic-steps').value=14;toast('Light traffic selected: 1 packet/step for 14 steps. Click Run simulation.');};
  $('traffic-heavy').onclick=()=>{$('traffic-rate').value=12;$('traffic-steps').value=12;toast('Stress test selected: 12 packets/step for 12 steps. Click Run simulation.');};
  $('congestion-threshold').oninput=e=>$('congestion-threshold-label').textContent=e.target.value+'%';
  $('congestion-save-policy').onclick=()=>safeAction({op:'congestion_settings',enabled:$('congestion-enabled').checked,threshold:Number($('congestion-threshold').value)/100});
  const jump = id=>$(id).scrollIntoView({behavior:'smooth',block:'start'});
  $('nav-scenarios').onclick=()=>jump('scenario-section');
  $('jump-traffic').onclick=()=>jump('traffic-panel');
  $('jump-attack').onclick=()=>jump('attack-panel');
  $('jump-congestion').onclick=()=>jump('congestion-panel');
  $('tick-speed').oninput=e=>$('speed-label').textContent=e.target.value+' ms';
  $('run-btn').onclick=runSimulation;
  $('step-btn').onclick=()=>simulateOne(Number($('traffic-rate').value));
  $('drain-btn').onclick=()=>simulateOne(0);
  $('preview-btn').onclick=()=>safeAction({op:'preview',source:$('source-select').value,target:$('target-select').value});
  $('compare-btn').onclick=async()=>{
    if(await safeAction({op:'compare',source:$('source-select').value,target:$('target-select').value})) {
      const {dijkstra,qlearning}=state.latest;
      toast('Dijkstra: '+(dijkstra?.join(' → ')||'No route')+'  |  Q-Learning: '+(qlearning?.join(' → ')||'No route'));
    }
  };
  $('fit-btn').onclick=()=>{$('network-svg').setAttribute('viewBox','0 0 900 530');toast('Canvas fitted to workspace');};
  $('reset-sim').onclick=()=>safeAction({op:'reset_simulation'});
  $('example-btn').onclick=()=>{if(confirm('Load example and reset the current simulation?')){selection=null;safeAction({op:'load_example'});}};
  $('clear-btn').onclick=()=>{if(confirm('Remove all devices and reset the simulation?')){selection=null;safeAction({op:'clear_network'});}};
  $('export-btn').onclick=()=>{location.href='/api/export';};
  $('import-btn').onclick=()=>$('import-input').click();
  $('import-input').onchange=async e=>{
    const file=e.target.files[0];if(!file)return;
    try {const topology=JSON.parse(await file.text());selection=null;await safeAction({op:'import',topology});}
    catch(err){toast('Cannot read JSON: '+err.message,true);}e.target.value='';
  };
  $('nav-topology').onclick=()=>{$('network-section').scrollIntoView({behavior:'smooth'});};
  $('nav-agent').onclick=()=>{$('activity-section').scrollIntoView({behavior:'smooth'});};
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'){setConnectMode(false);closeAdd();}
    if((e.key==='Delete'||e.key==='Backspace') && selection && $('modal-overlay').hidden) {
      const tag=document.activeElement?.tagName;
      if(['INPUT','TEXTAREA','SELECT'].includes(tag))return;
      if(selection.type==='node')deleteDevice(selection.name);
      else if(selection.type==='link')deleteLink(selection.key);
    }
  });
}
(async function init(){
  bindEvents();
  try {state=await getState();$('route-mode').value=state.mode;render();}
  catch(e){toast('Start the Python server with: py server.py',true);}
})();

// STEP 8: Main Agent mission interface. Planning is read-only until approved.
let pendingMission = null;
async function missionRequest(endpoint, payload) {
  const res = await fetch(endpoint, {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const answer = await res.json();
  if (!res.ok) throw new Error(answer.error || 'Mission request failed');
  return answer;
}
function setMissionBusy(value, label) {
  const btn = $('mission-plan');
  btn.disabled = value;
  btn.querySelector('span').textContent = label || 'Review plan';
}
async function planMission() {
  $('mission-error').hidden = true;
  $('mission-complete').hidden = true;
  $('mission-proposal').hidden = true;
  pendingMission = null;
  setMissionBusy(true,'Assessing topology…');
  try {
    const answer = await missionRequest('/api/mission', {message:$('mission-input').value.trim()});
    pendingMission = answer.mission_id;
    const p = answer.proposal;
    $('mission-summary').textContent = p.summary;
    $('mission-source-mode').textContent = p.mode.toUpperCase();
    $('mission-note').textContent = p.note || 'Main Agent will coordinate the specialized agents and check the result after approval.';
    $('mission-proposal').hidden = false;
    $('mission-proposal').scrollIntoView({block:'nearest', behavior:'smooth'});
  } catch (err) {
    $('mission-error').textContent = err.message;
    $('mission-error').hidden = false;
  } finally {setMissionBusy(false);}
}
async function executeMission() {
  if (!pendingMission) return;
  const id = pendingMission;
  const btn = $('mission-execute');
  btn.disabled = true;
  btn.textContent = 'Agents executing…';
  try {
    const answer = await missionRequest('/api/mission/execute',{mission_id:id});
    pendingMission = null;
    state = answer.state;
    render();
    $('mission-proposal').hidden = true;
    $('mission-complete').textContent = '✓ CHECK COMPLETE  •  '+answer.report.outcome;
    $('mission-complete').hidden = false;
    toast('Main Agent finished: '+answer.report.summary);
  } catch(err) {
    $('mission-error').textContent = err.message;
    $('mission-error').hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Execute plan';
  }
}
function initMissions(){
  $('mission-plan').addEventListener('click',planMission);
  $('mission-execute').addEventListener('click',executeMission);
  $('mission-discard').addEventListener('click',()=>{pendingMission=null;$('mission-proposal').hidden=true;});
  document.querySelectorAll('[data-mission]').forEach(btn=>btn.addEventListener('click',()=>{
    const src=$('source-select').value||'PC1', dst=$('target-select').value||'S1';
    const target=$('attack-device').value||'R2';
    $('mission-input').value={
      route:`Find the best route from ${src} to ${dst}`,
      attack:`Simulate blackhole on ${target}`,
      traffic:`Send 4 packets per step from ${src} to ${dst} for 10 steps`,
    }[btn.dataset.mission];
    $('mission-input').focus();
  }));
  getState().then(s=>{
    $('planner-mode').textContent=s.llm_enabled?'Gemini-assisted planning ready':'Offline reasoning · optional Gemini';
  }).catch(()=>{});
}
initMissions();
