/* Host updater settings. No credentials are persisted in browser storage. */
(() => {
  const byId = id => document.getElementById(id);
  let busy = false;
  const date = value => value ? new Date(value * 1000).toLocaleString() : 'Not yet';
  async function request(path = '', data) {
    const options = {cache: 'no-store', credentials: 'same-origin'};
    if (data !== undefined) Object.assign(options, {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-ChassisDeck-Update': '1'}, body: JSON.stringify(data)});
    const response = await fetch('/hardware/api/updates' + path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Update service unavailable');
    return result;
  }
  async function refresh() {
    try {
      const data = await request(), s = data.status || {};
      byId('updates-current').textContent = s.current_version || 'Unknown';
      byId('updates-latest').textContent = s.available_version || 'Awaiting check';
      byId('updates-checked').textContent = date(s.checked_at);
      byId('updates-installed').textContent = date(s.updated_at);
      byId('updates-message').textContent = s.message || 'Waiting for host updater';
      byId('updates-state').textContent = s.state || 'Waiting';
      byId('updates-toggle').checked = data.settings.auto_enabled === true;
      byId('updates-toggle').disabled = !data.authenticated || busy;
      byId('updates-enabled').textContent = data.settings.auto_enabled ? 'On' : 'Off';
      byId('updates-unlock').hidden = data.authenticated;
      byId('updates-lock').hidden = !data.authenticated;
      byId('updates-check').disabled = !data.authenticated || busy;
    } catch (_) {
      byId('updates-message').textContent = 'The host update service is unavailable. Settings have not changed.';
      byId('updates-state').textContent = 'Unavailable';
      byId('updates-enabled').textContent = 'Unknown';
      byId('updates-toggle').disabled = true;
      byId('updates-check').disabled = true;
      byId('updates-unlock').hidden = true;
      byId('updates-lock').hidden = true;
      try {
        const response = await fetch('/hardware/assets/build-info.json', {cache: 'no-store'});
        if (response.ok) byId('updates-current').textContent = (await response.json()).version || 'Development build';
      } catch (_) { /* Keep the last known release when offline. */ }
    }
  }
  async function action(path, data) {
    if (busy) return;
    busy = true;
    byId('updates-feedback').textContent = 'Saving…';
    byId('updates-toggle').disabled = true;
    byId('updates-check').disabled = true;
    try {
      const result = await request(path, data);
      byId('updates-feedback').textContent = result.message || (path === '/login' ? 'Settings unlocked for one hour.' : 'Settings locked.');
    } catch (error) { byId('updates-feedback').textContent = error.message; }
    finally { busy = false; await refresh(); }
  }
  function init() {
    byId('updates-unlock').addEventListener('submit', event => {
      event.preventDefault();
      const key = byId('updates-key').value;
      byId('updates-key').value = '';
      action('/login', {token: key});
    });
    byId('updates-toggle').addEventListener('change', event => action('/settings', {auto_enabled: event.target.checked}));
    byId('updates-lock').addEventListener('click', () => action('/logout', {}));
    byId('updates-check').addEventListener('click', () => action('/check', {}));
    if (location.hash === '#updates') refresh();
    setInterval(() => { if (!byId('tab-updates').hidden && !busy) refresh(); }, 15000);
  }
  window.chassisDeckUpdatesRefresh = refresh;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
