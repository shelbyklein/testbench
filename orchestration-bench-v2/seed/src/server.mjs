import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createStore} from './store.mjs';
import {createService} from './service.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const store = createStore(process.env.DATA_FILE || path.join(root, 'data', 'notes.json'));
const service = createService(store);
const json = (res, status, value) => {res.writeHead(status, {'Content-Type': 'application/json'}); res.end(JSON.stringify(value));};
export async function readJSON(req) {
  let body = '';
  for await (const chunk of req) {
    body += chunk;
    if (body.length > 1_000_000) { const e = new Error('Request too large'); e.status = 413; throw e; }
  }
  try { return JSON.parse(body || '{}'); }
  catch { const e = new Error('Invalid JSON'); e.status = 400; throw e; }
}
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');
    if (req.method === 'GET' && url.pathname === '/api/state') return json(res, 200, service.state());
    if (req.method === 'GET' && url.pathname === '/api/notes') return json(res, 200, {notes: service.list({folderId: url.searchParams.get('folderId') || '', query: url.searchParams.get('q') || '', includeArchived: url.searchParams.get('includeArchived') === 'true'})});
    const archive = url.pathname.match(/^\/api\/notes\/([^/]+)\/archive$/);
    if (req.method === 'POST' && archive) return json(res, 200, service.archive(decodeURIComponent(archive[1])));
    if (url.pathname.startsWith('/api/')) return json(res, 404, {error: 'Not found'});
    const files = {'/': ['index.html', 'text/html'], '/app.mjs': ['app.mjs', 'text/javascript'], '/styles.css': ['styles.css', 'text/css']};
    if (req.method !== 'GET' || !files[url.pathname]) {res.writeHead(404); return res.end('Not found');}
    const [file, type] = files[url.pathname];
    res.writeHead(200, {'Content-Type': type}); res.end(fs.readFileSync(path.join(root, 'web', file)));
  } catch (error) {json(res, error.status || 500, {error: error.message});}
});
server.listen(Number(process.env.PORT || 4310), '127.0.0.1', () => console.log(`Fieldnotes listening at http://127.0.0.1:${server.address().port}`));
