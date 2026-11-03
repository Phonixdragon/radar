let adminCsrf = '';
let adminUnlocked = false;
let lastState = null;
const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $('toast'); el.textContent = message; el.classList.add('show');
  clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
}
function showResult(id, html, isError=false) {
  const el = $(id); el.innerHTML = html; el.classList.remove('hidden','error');
  if (isError) el.classList.add('error');
}
async function api(url, options={}) {
  const headers = {'Content-Type':'application/json', ...(options.headers||{})};
  if (adminCsrf && url.startsWith('/api/admin/') && options.method && options.method !== 'GET') headers['X-PV-CSRF'] = adminCsrf;
  const response = await fetch(url, {...options, headers});
  let data; try { data = await response.json(); } catch { data = {ok:false,error:'Unexpected server response.'}; }
  if (!response.ok || data.ok === false) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function slotCard(slot) {
  const statusClass = slot.status.toLowerCase().replace(' ','-');
  return `<article class="slot-card"><div class="slot-top"><span class="slot-id">${escapeHtml(slot.id)}</span><span class="status ${statusClass}">${escapeHtml(slot.status)}</span></div><h3>${escapeHtml(slot.label)}</h3><p>${escapeHtml(slot.note)}</p><span class="kind">${slot.kind === 'physical' ? '● LIVE HARDWARE CONNECTED' : '○ SOFTWARE SIMULATION'}</span></article>`;
}
async function refreshState() {
  try {
    const data = await api('/api/state'); lastState = data;
    $('slotsGrid').innerHTML = data.slots.map(slotCard).join('');
    const p = data.slots.find(s => s.id === 'P-01');
    $('physicalStatus').textContent = data.occupied ? 'OCCUPIED' : 'CLEAR';
    $('physicalStatus').style.color = data.occupied ? 'var(--red)' : 'var(--green)';
    $('distanceReadout').textContent = data.distance_cm == null ? 'Distance: waiting for sensor' : `Distance: ${Number(data.distance_cm).toFixed(1)} cm`;
    $('gateStatus').textContent = data.gate;
    $('gateStatus').style.color = data.gate === 'OPEN' ? 'var(--amber)' : 'var(--green)';
    $('connectionStatus').textContent = data.mode === 'demo' ? 'SIMULATOR' : (data.connected ? 'CONNECTED' : 'OFFLINE');
    $('connectionStatus').style.color = data.mode === 'demo' ? 'var(--blue)' : (data.connected ? 'var(--green)' : 'var(--red)');
    $('modeText').textContent = data.mode === 'demo' ? 'Software-only test mode' : (data.serial_error || 'Arduino · USB serial');
    $('lastUpdated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
    if (adminUnlocked) { $('adminBayState').textContent = data.occupied ? 'OCCUPIED' : 'CLEAR'; $('adminGateState').textContent = data.gate; }
  } catch (err) { $('lastUpdated').textContent = 'Server connection lost'; }
}
$('bookingForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const data = await api('/api/book', {method:'POST', body:JSON.stringify({visitor_name:$('visitorName').value,slot_id:$('slotSelect').value,duration_minutes:Number($('duration').value)})});
    showResult('bookingResult', `<b>Reservation created</b><br>Booking ID: <strong>${escapeHtml(data.booking_id)}</strong><br>Access code: <strong>${escapeHtml(data.access_code)}</strong><br>Bay: ${escapeHtml(data.slot_id)} · Expires: ${new Date(data.expires_at).toLocaleTimeString()}<br><small>Save both values. You need them to check in.</small>`);
    $('bookingId').value = data.booking_id; $('accessCode').value = data.access_code;
    toast('Reservation created'); refreshState(); loadAdmin();
  } catch (err) { showResult('bookingResult', escapeHtml(err.message), true); }
});
$('checkinForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const data = await api('/api/checkin', {method:'POST',body:JSON.stringify({booking_id:$('bookingId').value,access_code:$('accessCode').value})});
    showResult('checkinResult', `<b>Check-in accepted</b><br>${escapeHtml(data.message)}`); toast('Check-in confirmed'); refreshState(); loadAdmin();
  } catch (err) { showResult('checkinResult', escapeHtml(err.message), true); }
});
$('adminToggle').addEventListener('click', () => $('adminPanel').classList.toggle('hidden'));
$('adminLoginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const data = await api('/api/admin/login', {method:'POST',body:JSON.stringify({password:$('adminPassword').value})});
    adminCsrf = data.csrf; adminUnlocked = true; $('adminLoginArea').classList.add('hidden'); $('adminControls').classList.remove('hidden'); $('adminPassword').value='';
    loadAdmin(); toast('Operator console unlocked');
  } catch (err) { toast(err.message); }
});
async function loadAdmin() {
  if (!adminUnlocked) return;
  try {
    const data = await api('/api/admin/overview');
    $('bookingTable').innerHTML = tableHtml(['ID','BAY','NAME','STATUS'], data.bookings.map(b=>[b.id,b.slot_id,b.visitor_name,b.status]));
    $('eventTable').innerHTML = tableHtml(['TIME','EVENT','DETAILS'], data.events.map(x=>[new Date(x.recorded_at).toLocaleTimeString(),x.event_type,x.details]));
  } catch (err) { toast(err.message); }
}
function tableHtml(headers, rows) {
  if (!rows.length) return '<small>No records yet.</small>';
  return `<table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${escapeHtml(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
async function adminPost(path, body={}) { await api(path,{method:'POST',body:JSON.stringify(body)}); await refreshState(); await loadAdmin(); }
$('demoOccupied').addEventListener('click', async()=>{try{await adminPost('/api/admin/demo-occupancy',{occupied:true});toast('Demo bay marked occupied');}catch(e){toast(e.message);}});
$('demoClear').addEventListener('click', async()=>{try{await adminPost('/api/admin/demo-occupancy',{occupied:false});toast('Demo bay marked clear');}catch(e){toast(e.message);}});
$('openGate').addEventListener('click', async()=>{try{await adminPost('/api/admin/gate',{action:'open'});toast('Gate open command sent');}catch(e){toast(e.message);}});
$('closeGate').addEventListener('click', async()=>{try{await adminPost('/api/admin/gate',{action:'close'});toast('Gate close command sent');}catch(e){toast(e.message);}});
$('logoutBtn').addEventListener('click', async()=>{try{await api('/api/admin/logout',{method:'POST',body:'{}'});}catch{} adminUnlocked=false;adminCsrf='';$('adminLoginArea').classList.remove('hidden');$('adminControls').classList.add('hidden');toast('Logged out');});
$('themeBtn').addEventListener('click',()=>{document.body.classList.toggle('light');localStorage.setItem('pv-theme',document.body.classList.contains('light')?'light':'dark');});
if (localStorage.getItem('pv-theme') === 'light') document.body.classList.add('light');
refreshState(); setInterval(refreshState,2000);
