const $ = selector => document.querySelector(selector);
const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
let requestVersion = 0;
async function api(url, options) {const response = await fetch(url, options); const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Request failed'); return data;}
async function render() {
  const version = ++requestVersion;
  try {
    const params = new URLSearchParams({q: $('#search').value, folderId: $('#folder').value, includeArchived: String($('#archived').checked)});
    const {notes} = await api(`/api/notes?${params}`);
    if (version !== requestVersion) return;
    $('#notes').innerHTML = notes.map(note => `<article><div class="tags">${note.tags.map(escape).join(' · ')}</div><h2>${escape(note.title)}</h2><p>${escape(note.body)}</p><footer><span>${escape(note.folderId)}${note.archived ? ' · Archived' : ''}</span>${note.archived ? '' : `<button data-archive="${escape(note.id)}">Archive<span class="sr-only"> ${escape(note.title)}</span></button>`}</footer></article>`).join('') || '<p class="empty">No notes here yet.</p>';
    $('#status').textContent = `${notes.length} note${notes.length === 1 ? '' : 's'}`;
  } catch(error) {$('#status').textContent = error.message;}
}
$('#search').addEventListener('input', render);
$('#folder').addEventListener('change', render);
$('#archived').addEventListener('change', render);
$('#notes').addEventListener('click', async event => {
  const button = event.target.closest('[data-archive]');
  if (!button) return;
  try {await api(`/api/notes/${encodeURIComponent(button.dataset.archive)}/archive`, {method:'POST'}); await render();}
  catch(error) {$('#status').textContent = error.message;}
});
try {
  const state = await api('/api/state');
  $('#folder').insertAdjacentHTML('beforeend', state.folders.map(folder => `<option value="${escape(folder.id)}">${escape(folder.name)}</option>`).join(''));
  await render();
} catch(error) {$('#status').textContent = error.message;}
