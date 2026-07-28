const ID = 'ensemble-studio-modal';
const API = '/api/ensemble';
const state = { sessionId: null, target: 'room', mode: 'auto', running: false, connected: false, controller:null, events: [], artifacts: [], decisions: [], usage:{local_calls:0,cloud_calls:0,estimated_cloud_input_tokens:0,estimated_cloud_output_tokens:0} };
const modes = [
  ['local_draft','Local Draft'], ['local_council','Local Council'], ['auto','Auto'],
  ['claude_review','Claude Review'], ['gpt_build','GPT Build'], ['full_council','Full Council']
];
const esc = (s='') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clock = value => value ? new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});

async function api(path='', options={}) {
  const response = await fetch(`${API}${path}`, {headers:{'Content-Type':'application/json', ...(options.headers||{})}, ...options});
  if (!response.ok) { const data=await response.json().catch(()=>({})); const error=new Error(data.detail?.action||data.detail?.error||`Ensemble API ${response.status}`); error.status=response.status; error.data=data; throw error; }
  return response.json();
}
function chair(name, model, resource) {
  return `<div class="ensemble-chair"><span class="ensemble-avatar">${esc(name[0])}</span><div><strong>${esc(name)}</strong><div class="ensemble-badges"><span class="ensemble-badge">${esc(model)}</span><span class="ensemble-badge">${esc(resource)}</span></div></div></div>`;
}
function build() {
  const modal = document.createElement('section'); modal.id = ID; modal.className = 'ensemble-view hidden';
  modal.innerHTML = `<div class="ensemble-window" role="region" aria-label="J-Space Studio">
    <div class="modal-header"><div class="ensemble-title"><div><div class="ensemble-kicker">J-Space Studio</div><h4>Ensemble Room</h4></div><span class="ensemble-status" data-state="ready">connecting</span></div><div class="ensemble-header-actions"><button data-new-session title="Start a fresh ensemble session">New Session</button><button data-close title="Return to the normal chat">Back to Chat</button></div></div>
    <div class="modal-body ensemble-body"><main class="ensemble-main">
      <div class="ensemble-chairs">${chair('Shaun','director','human')}${chair('Claude','Claude','continuity · judgment')}${chair('GPT / Codex','GPT / Codex','building · tools')}</div>
      <div class="ensemble-baton" aria-label="Baton controls">${modes.map(([k,l])=>`<button data-mode="${k}" class="${k==='auto'?'active':''}">${l}</button>`).join('')}<button class="ensemble-stop" data-stop>Stop</button></div>
      <div class="ensemble-usage"><strong>LOCAL-FIRST</strong><span data-usage>0 local · 0 cloud · ~0 cloud tokens</span></div>
      <div class="ensemble-timeline" aria-live="polite"></div>
      <div class="ensemble-compose"><div class="ensemble-targets">${['claude','gpt','room'].map(x=>`<button class="ensemble-target ${x==='room'?'active':''}" data-target="${x}">@${x}</button>`).join('')}</div><div class="ensemble-input-row"><textarea class="ensemble-input" placeholder="Brief the room… (⌘/Ctrl+Enter to send)" aria-label="Message to ensemble"></textarea><button class="ensemble-send">Send</button></div></div>
    </main><aside class="ensemble-rail"><section class="ensemble-rail-section"><h5>Artifacts</h5><div data-artifacts></div></section><section class="ensemble-rail-section"><h5>Decisions</h5><div data-decisions></div></section></aside></div></div>`;
  (document.getElementById('chat-container')||document.body).appendChild(modal);
  modal.querySelector('[data-close]').onclick = close;
  modal.querySelector('[data-new-session]').onclick = () => startSession(true);
  modal.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => { state.mode=b.dataset.mode; modal.querySelectorAll('[data-mode]').forEach(x=>x.classList.toggle('active',x===b)); });
  modal.querySelectorAll('[data-target]').forEach(b => b.onclick = () => { state.target=b.dataset.target; modal.querySelectorAll('[data-target]').forEach(x=>x.classList.toggle('active',x===b)); modal.querySelector('.ensemble-input').focus(); });
  modal.querySelector('[data-stop]').onclick = stop;
  modal.querySelector('.ensemble-send').onclick = send;
  modal.querySelector('.ensemble-input').onkeydown = e => { if ((e.metaKey||e.ctrlKey)&&e.key==='Enter') send(); };
  render(); startSession(false);
  return modal;
}
function render() {
  const modal=document.getElementById(ID); if(!modal)return;
  modal.querySelector('.ensemble-timeline').innerHTML=state.events.length ? state.events.map(e=>`<article class="ensemble-event" data-speaker="${esc(e.speaker)}"><div class="ensemble-event-head"><strong>${esc(e.label||e.speaker)}</strong>${e.model?`<span class="ensemble-badge">${esc(e.model)}</span>`:''}<time>${esc(e.time||clock(e.timestamp))}</time></div><p>${esc(e.text||e.content)}</p></article>`).join('') : '<div class="ensemble-empty">Opening the shared room…</div>';
  const timeline=modal.querySelector('.ensemble-timeline'); timeline.scrollTop=timeline.scrollHeight;
  modal.querySelector('[data-artifacts]').innerHTML=state.artifacts.length?state.artifacts.map(a=>`<div class="ensemble-rail-item"><strong>${esc(a.title||a.name||'Artifact')}</strong><div>${esc(a.kind||a.artifact_type||a.path||a.uri||'output')}</div></div>`).join(''):'<div class="ensemble-empty">Files and outputs appear here.</div>';
  modal.querySelector('[data-decisions]').innerHTML=state.decisions.length?state.decisions.map(d=>`<div class="ensemble-rail-item ensemble-decision">${esc(d.text||d.content||d)}</div>`).join(''):'<div class="ensemble-empty">Council decisions appear here.</div>';
  const u=state.usage, usage=modal.querySelector('[data-usage]'); if(usage)usage.textContent=`${u.local_calls||0} local · ${u.cloud_calls||0} cloud · ~${(u.estimated_cloud_input_tokens||0)+(u.estimated_cloud_output_tokens||0)} cloud tokens`;
}
function hydrate(detail) {
  state.sessionId=detail.id;
  state.events=(detail.turns||[]).map(t=>({speaker:t.participant.toLowerCase()==='gpt'?'gpt':t.participant.toLowerCase(),label:t.participant,text:t.content,timestamp:t.timestamp}));
  state.artifacts=detail.artifacts||[]; state.decisions=detail.decisions||[]; render();
}
async function startSession(forceNew=false) {
  setStatus('connecting', true);
  try {
    let session;
    if (!forceNew) { const list=await api('/sessions'); session=list.sessions?.[0]; }
    if (!session) session=await api('/sessions',{method:'POST',body:JSON.stringify({title:`Studio Session · ${new Date().toLocaleString()}`})});
    hydrate(await api(`/sessions/${session.id}`)); state.connected=true;
    const chairs=await api('/status').catch(()=>null);
    setStatus(chairs ? `Local ${chairs.local?.ready?'live':'setup'} · Claude ${chairs.claude.ready?'live':'setup'} · GPT ${chairs.gpt.ready?'live':'setup'}` : 'connected');
  } catch (error) {
    state.connected=false; state.sessionId=null;
    if (!state.events.length) state.events=[{speaker:'room',label:'Room',text:'The room is available in local demo mode. Persistence will reconnect when the Ensemble API is live.',time:clock()}];
    render(); setStatus('local demo'); console.warn(error);
  }
}
async function persistTurn(participant, role, content) {
  if (!state.connected || !state.sessionId) return;
  await api(`/sessions/${state.sessionId}/turns`,{method:'POST',body:JSON.stringify({participant,role,content})});
}
function appendEvent(event, persist=true){ state.events.push({...event,time:event.time||clock()}); render(); if(persist && ['claude','gpt'].includes(event.speaker)) persistTurn(event.speaker==='claude'?'Claude':'GPT','ai',event.text).catch(console.warn); }
function setStatus(label, running=false){ const el=document.querySelector(`#${ID} .ensemble-status`); if(el){el.dataset.state=running?'running':'ready';el.textContent=label;} }
function setRunning(on,label){ state.running=on; setStatus(label||(on?'running':(state.connected?'connected':'local demo')),on); }
async function send(){ const input=document.querySelector(`#${ID} .ensemble-input`); const message=input?.value.trim(); if(!message||state.running)return; input.value=''; appendEvent({speaker:'shaun',label:`Shaun · @${state.target}`,text:message},false); setRunning(true);
  try { await persistTurn('Shaun','human',message); } catch(error) { console.warn(error); state.connected=false; }
  const detail={text:message,target:state.target,mode:state.mode,sessionId:state.sessionId,handled:false,append:appendEvent,artifact:addArtifact,decision:addDecision,complete:()=>setRunning(false)};
  window.dispatchEvent(new CustomEvent('odysseus:ensemble-run',{detail}));
  if(!detail.handled) runLive(message);
}
async function runLive(message){
  try {
    state.controller=new AbortController();
    const result=await api(`/sessions/${state.sessionId}/run`,{method:'POST',signal:state.controller.signal,body:JSON.stringify({text:message,target:state.target,mode:state.mode})});
    for(const turn of result.turns||[]) appendEvent({speaker:turn.speaker,label:`${turn.participant} · ${turn.purpose}`,model:turn.model,text:turn.content},false);
    const u=result.usage||{}; for(const key of Object.keys(state.usage))state.usage[key]+=(u[key]||0); render();
    state.controller=null; setRunning(false,'live');
  } catch(error) {
    state.controller=null;
    if(error.name==='AbortError'){setRunning(false,'stopped');return;}
    appendEvent({speaker:'room',label:'Setup needed',text:error.message},false);
    setRunning(false,error.status===409?'setup needed':'error');
  }
}
function demo(message){ const sequence=state.mode==='solo_claude'?[['claude','Claude']]:state.mode==='solo_gpt'?[['gpt','GPT / Codex']]:state.mode==='gpt_to_claude'?[['gpt','GPT / Codex'],['claude','Claude · review']]:state.mode==='claude_to_gpt'?[['claude','Claude'],['gpt','GPT / Codex · review']]:[['claude','Claude'],['gpt','GPT / Codex']]; sequence.forEach(([speaker,label],i)=>setTimeout(()=>{if(!state.running)return; appendEvent({speaker,label,model:speaker==='claude'?'demo · Claude':'demo · Codex',text:i?`Review: I would test the proposal against workspace constraints and reconcile differences before committing.`:`Demo response: I received “${message.slice(0,90)}”. Attach a chair runner to odysseus:ensemble-run for live inference.`}); if(i===sequence.length-1){if(state.mode==='council_one_round')addDecision({text:'One-round council completed; Shaun retains the baton.',created_by:'Claude'});setRunning(false);}},450+i*650)); }
function stop(){ state.controller?.abort(); state.controller=null; state.running=false; if(state.sessionId)api(`/sessions/${state.sessionId}/stop`,{method:'POST'}).catch(()=>{}); window.dispatchEvent(new CustomEvent('odysseus:ensemble-stop',{detail:{sessionId:state.sessionId}})); setRunning(false,'stopped'); }
function addArtifact(a){ state.artifacts.push(a);render(); if(state.connected&&state.sessionId)api(`/sessions/${state.sessionId}/artifacts`,{method:'POST',body:JSON.stringify({name:a.title||a.name||'Artifact',artifact_type:a.kind||a.artifact_type||'output',uri:a.path||a.uri||null,metadata:a.metadata||{},created_by:a.created_by||'GPT'})}).catch(console.warn); }
function addDecision(d){state.decisions.push(d);render();if(state.connected&&state.sessionId)api(`/sessions/${state.sessionId}/decisions`,{method:'POST',body:JSON.stringify({content:d.text||d.content||String(d),created_by:d.created_by||'Claude'})}).catch(console.warn);}
function open(){ let modal=document.getElementById(ID); if(!modal)modal=build(); document.getElementById('chat-container')?.classList.add('ensemble-active'); modal.classList.remove('hidden'); }
function close(){ stop(); document.getElementById(ID)?.classList.add('hidden'); document.getElementById('chat-container')?.classList.remove('ensemble-active'); }
function toggleStudio(){ const modal=document.getElementById(ID); if(modal&&!modal.classList.contains('hidden'))close(); else open(); }
document.getElementById('rail-ensemble')?.addEventListener('click',toggleStudio);
document.getElementById('tool-ensemble-btn')?.addEventListener('click',toggleStudio);
document.addEventListener('click',e=>{const nav=e.target.closest('#sidebar .list-item,.icon-rail-btn');if(nav&&!['tool-ensemble-btn','rail-ensemble'].includes(nav.id))close();});
window.EnsembleStudio={open,close,append:appendEvent,addArtifact,addDecision,stop,newSession:()=>startSession(true),state};
