const $ = (id) => document.getElementById(id);
let dates = [], runs = [], selectedRun, selectedDate, railStart, busy = false, timer, zone = 'America/Edmonton', selectionRequest = 0;
let devMode = false, demoArchive = [], previewFromSettings = false;
const node = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
async function api(path, options = {}) { if (devMode) return demoResponse(path, options, demoArchive, zone); const r = await fetch(path, options); if (!r.ok) { const data = await r.json().catch(() => ({})); throw new Error(data.detail || 'Could not connect to Rundown'); } return r.json(); }
function notice(text, error = false) { $('notice').replaceChildren(); if (text) $('notice').append(node('div', text, `notice${error ? ' error' : ''}`)); }
function dayKey(d) { return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function localDay(key) { return new Date(`${key}T12:00:00`); }
function today() { return new Intl.DateTimeFormat('en-CA', {timeZone:zone, year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); }
function formatTime(value) { return new Date(value).toLocaleTimeString([], {timeZone:zone, hour:'numeric', minute:'2-digit'}); }
function centerRail() { railStart = localDay(selectedDate); railStart.setDate(railStart.getDate()-3); }
function renderCalendar() {
  $('dates').replaceChildren();
  $('month').textContent = localDay(selectedDate).toLocaleDateString([], {month:'long',year:'numeric'});
  $('date-picker').value = selectedDate;
  for (let i=0;i<7;i++) {
    const d = new Date(railStart); d.setDate(d.getDate()+i); const key = dayKey(d);
    const has = dates.some(x => x.date === key);
    const b = node('button', undefined, `date${has ? ' has-run' : ''}${key === selectedDate ? ' selected' : ''}`);
    b.setAttribute('aria-label', `${d.toDateString()}${has ? ', saved digests' : ', no digests'}`); b.setAttribute('aria-pressed', String(key === selectedDate));
    b.append(node('span', d.toLocaleDateString([], {weekday:'short'}), 'weekday'), node('span', d.getDate(), 'number'));
    b.onclick = () => selectDate(key).catch(e=>notice(e.message,true)); $('dates').append(b);
  }
}
async function selectDate(key) { const request=++selectionRequest; selectedDate=key; renderCalendar(); const result = await api(`/api/digests?date=${encodeURIComponent(key)}`); if(request!==selectionRequest)return; runs=result; selectedRun=runs[0]; renderRunSelector(); render(); }
function renderRunSelector() { $('runs').replaceChildren(); for (const [index,r] of runs.entries()) { const option=node('option', `${formatTime(r.started_at)} · Run ${runs.length-index} · ${r.status}`); option.value=r.id; $('runs').append(option); } $('runs').hidden=runs.length<2; }
function render() {
  const channelValue=$('channels').value;
  $('channels').replaceChildren(new Option('All channels',''));
  for (const c of selectedRun?.channels || []) $('channels').append(new Option(c.channel_name,c.channel_id));
  if ([...$('channels').options].some(o=>o.value===channelValue)) $('channels').value=channelValue;
  $('day-title').textContent=localDay(selectedDate).toLocaleDateString([], {weekday:'long',month:'long',day:'numeric'});
  $('run-meta').textContent=selectedRun ? `${formatTime(selectedRun.started_at)} · ${selectedRun.status} · ${selectedRun.model || selectedRun.provider}` : 'No digest saved for this day.';
  $('errors').replaceChildren();
  for (const e of selectedRun?.errors || []) $('errors').append(node('div',`${e.channel}: ${e.error}`,'run-error'));
  $('metrics').replaceChildren(); $('metrics').hidden=!selectedRun;
  if (selectedRun) {
    const channels=selectedRun.channels;
    for (const [value,label] of [[channels.length,'channels'],[channels.reduce((n,c)=>n+c.message_count,0),'new messages'],[channels.reduce((n,c)=>n+c.digest.action_items.length,0),'action items']]) { const m=node('div',undefined,'metric');m.append(node('strong',value),node('span',label));$('metrics').append(m); }
  }
  renderCards();
}
function safeSlackLink(value) { try {const u=new URL(value); return u.protocol==='https:' && (u.hostname==='slack.com'||u.hostname.endsWith('.slack.com')) ? u.href : null;} catch {return null;} }
function renderCards() {
  const query=$('search').value.toLowerCase(), channel=$('channels').value;
  const all=selectedRun?.channels || [];
  const filtered=all.filter(c=>(!channel||c.channel_id===channel)&&JSON.stringify(c).toLowerCase().includes(query));
  $('cards').replaceChildren();
  for (const c of filtered) {
    const d=c.digest, card=node('article',undefined,'card'), top=node('div',undefined,'card-top'), title=node('h3',undefined,'channel-name');
    title.append(node('span','#'),document.createTextNode(c.channel_name)); top.append(title,node('span',`${c.message_count} new message${c.message_count===1?'':'s'}`,'count')); card.append(top,node('p',d.overview,'overview'));
    for (const [key,label] of [['key_updates','Key updates'],['action_items','Action items'],['decisions','Decisions']]) if (d[key].length) { const s=node('section',undefined,'card-section'),list=node('ul');s.append(node('h3',label)); for (const item of d[key]) list.append(node('li',item));s.append(list);card.append(s); }
    if (d.priority_items.length) {
      const section=node('section',undefined,'priority');section.append(node('h3','Priority','priority-heading'));
      for (const item of d.priority_items) { const row=node('div',undefined,'priority-item'),meta=node('div',undefined,'priority-meta');row.append(node('p',item.explanation));meta.append(node('span',`${item.score} priority`,'badge score'));for (const keyword of item.matched_keywords) meta.append(node('span',keyword,'badge'));const href=safeSlackLink(item.slack_link);if (href) {const a=node('a','Open in Slack ↗');a.href=href;a.target='_blank';a.rel='noopener noreferrer';meta.append(a);}row.append(meta);section.append(row); }
      card.append(section);
    }
    $('cards').append(card);
  }
  $('empty').hidden=filtered.length>0;
  if (!filtered.length) {
    $('empty').querySelector('h2').textContent=all.length ? 'No matches' : 'No summaries';
    $('empty').querySelector('p').textContent=all.length ? 'Change the channel or search filter.' : selectedRun ? (selectedRun.status==='failed' ? 'Run failed. Check the errors above.' : 'No new messages in this run.') : dates.length ? 'Select a date with saved runs.' : 'Run a digest to get started.';
  }
}
async function checkConnections() { if (devMode) return; $('readiness').textContent='Checking connections…'; const status=await api('/api/status?check=true');if(devMode)return;const r=status.readiness;$('readiness').textContent=`Slack: ${r.slack.message}\n${r.provider_name==='ollama'?'Ollama':'Claude Code'}: ${r.provider.message}`;if (!r.ready) notice('Connections need attention. '+[r.slack,r.provider].filter(x=>!x.ready).map(x=>x.message).join(' · '),true); }
async function refresh(selectLatest=false) { const s=await api('/api/status');zone=s.timezone;$('timezone').textContent=zone;$('provider-label').textContent=devMode?'Sample data':s.provider_name==='ollama'?'Ollama':'Claude Code';busy=s.busy;$('run').disabled=busy||devMode;$('run').textContent=devMode?'Preview only':busy?'Running…':'Run now'; dates=await api('/api/dates'); if (!selectedDate||selectLatest) {selectedDate=dates[0]?.date || today(); centerRail();} await selectDate(selectedDate);if(busy&&!devMode){const r=s.latest;notice(r?`${r.processed} of ${r.total} channels processed`:'Digest running…');schedulePoll();} }
function schedulePoll(){clearTimeout(timer);timer=setTimeout(async()=>{try{const previous=busy;await refresh(false);if(previous&&!busy){notice('Your run has finished.');await refresh(true);}}catch(e){notice(e.message,true);schedulePoll();}},2000);}
$('run').onclick=async()=>{ if(devMode)return; $('run').disabled=true;try{await api('/api/runs',{method:'POST',headers:{'X-Rundown-Request':'1'}});await refresh(true);}catch(e){notice(e.message,true);$('run').disabled=false;} };
$('runs').onchange=()=>{selectedRun=runs.find(r=>r.id===$('runs').value);render();};
$('channels').onchange=renderCards;$('search').oninput=renderCards;
$('prev').onclick=()=>{railStart.setDate(railStart.getDate()-7);renderCalendar();};$('next').onclick=()=>{railStart.setDate(railStart.getDate()+7);renderCalendar();};
$('date-picker').onchange=()=>{if($('date-picker').value){selectedDate=$('date-picker').value;centerRail();selectDate(selectedDate).catch(e=>notice(e.message,true));}};
$('recheck').onclick=()=>checkConnections().catch(e=>notice(e.message,true));

async function togglePreview() {
  if ($('settings-form').getAttribute('aria-busy') === 'true') return;
  clearTimeout(timer); selectionRequest++;
  $('dev-toggle').disabled = true;
  try {
    if (!devMode) {
      previewFromSettings = !$('settings-screen').hidden;
      hideToken(); // Preserve unsaved setup fields, but never leave the token exposed.
      demoArchive = createDemoArchive(today());
      devMode = true;
    } else devMode = false;
    dates=[];runs=[];selectedDate=undefined;selectedRun=undefined;
    $('channels').value='';$('search').value='';notice('');
    $('dev-toggle').setAttribute('aria-pressed',String(devMode));
    $('dev-toggle').setAttribute('aria-label',devMode?'Exit developer preview':'Enable developer preview');
    $('dev-banner').hidden=!devMode;
    $('readiness').hidden=devMode;$('recheck').hidden=devMode;
    if (!devMode && previewFromSettings) {showSettings();return;}
    $('loading-screen').hidden=true;$('settings-screen').hidden=true;$('dashboard').hidden=false;
    $('settings-open').hidden=devMode;
    await refresh();
  } catch(error) {notice(error.message,true);}
  finally {$('dev-toggle').disabled=false;}
}
$('dev-toggle').onclick=togglePreview;
$('dev-exit').onclick=togglePreview;
