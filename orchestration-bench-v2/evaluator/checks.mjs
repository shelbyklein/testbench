// Operator-side tests. Never copy this file into an implementer's workspace.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import net from 'node:net';
const [scenario, candidateArg, output] = process.argv.slice(2);
if (!['S1','S2','S3'].includes(scenario) || !candidateArg || !output) throw new Error('Usage: node checks.mjs S1|S2|S3 CANDIDATE OUTPUT.json');
const candidate = path.resolve(candidateArg);
const results = [];
async function check(id, description, fn) {
  const start = Date.now();
  try {await fn(); results.push({id, description, status:'pass', durationMs:Date.now()-start});}
  catch (error) {results.push({id, description, status:'fail', evidence:String(error.stack || error).replaceAll(candidate,'<submission>').slice(0,4500), durationMs:Date.now()-start});}
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function startServer(dataFile) {
  const probe = net.createServer();
  await new Promise((resolve, reject) => {probe.once('error', reject); probe.listen(0, '127.0.0.1', resolve);});
  const port = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  const base = `http://127.0.0.1:${port}`;
  const child = spawn(process.execPath, ['src/server.mjs'], {cwd:candidate, env:{...process.env, PORT:String(port), DATA_FILE:dataFile}, stdio:['ignore','pipe','pipe']});
  let text = ''; let errors = '';
  child.stdout.on('data', chunk => {text += chunk;}); child.stderr.on('data', chunk => {errors += chunk;});
  child.on('error', error => {errors += error.message;});
  const stop = async () => {
    if (child.exitCode !== null || child.signalCode !== null) return;
    child.kill('SIGTERM');
    await Promise.race([new Promise(resolve => child.once('exit',resolve)), sleep(1000)]);
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  };
  const deadline = Date.now()+8000;
  while (Date.now() < deadline) {
    let ready = false;
    try {const response = await fetch(base + '/api/state', {signal:AbortSignal.timeout(300)}); await response.text(); ready = true;} catch {}
    if (ready) {
      return {stop, async request(route, {method='GET', body, raw}={}) {
        const response = await fetch(base+route, {method, headers:{'Content-Type':'application/json'}, ...(body !== undefined || raw !== undefined ? {body:raw ?? JSON.stringify(body)} : {}), signal:AbortSignal.timeout(6000)});
        const content = await response.text();
        let data; try {data = JSON.parse(content);} catch {throw new Error(`Non-JSON HTTP ${response.status}: ${content.slice(0,200)}`);}
        return {status:response.status, data};
      }};
    }
    if (child.exitCode !== null || errors.includes('ENOENT')) break;
    await sleep(30);
  }
  await stop(); throw new Error(`Candidate server did not start using the supplied PORT and DATA_FILE. ${errors.slice(0,1500)}`);
}
async function withServer(fn) {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(),'bench-eval-'));
  const dataFile = path.join(temp,'state.json');
  let server;
  try {
    server = await startServer(dataFile);
    await fn(server, async () => {await server.stop(); server = await startServer(dataFile); return server;});
  } finally {if (server) await server.stop(); fs.rmSync(temp,{recursive:true,force:true});}
}
function ok(response, expected=200) {assert.equal(response.status,expected,JSON.stringify(response.data)); return response.data;}
function errorResponse(response, expected) {const data = ok(response,expected); assert.equal(typeof data.error,'string'); assert.ok(data.error.trim());}
const state = async server => ok(await server.request('/api/state'));
const post = (server, route, body) => server.request(route,{method:'POST',body});
const portable = (id, extra={}) => ({id, folderId:'inbox',title:`Imported ${id}`,body:'A portable thought.',tags:['Portable'],archived:false,updatedAt:'2026-09-07T10:00:00.000Z',...extra});
const bundle = notes => ({version:1,notes});

await check('R1','Existing API exposes folders and notes',()=>withServer(async server => {
  const data = await state(server); assert.equal(data.notes.length,4); assert.equal(data.folders.length,3);
}));
await check('R2','Default listing excludes archives and is newest-first',()=>withServer(async server => {
  const data = ok(await server.request('/api/notes')); assert.deepEqual(data.notes.map(n=>n.id),['n4','n2','n1']);
}));
await check('R3','Archive persists and preserves other notes after restart',()=>withServer(async (server,restart) => {
  const before = await state(server); ok(await post(server,'/api/notes/n1/archive',{}));
  server = await restart(); const after = await state(server);
  assert.equal(after.notes.find(n=>n.id==='n1').archived,true);
  assert.deepEqual(after.notes.filter(n=>n.id!=='n1'),before.notes.filter(n=>n.id!=='n1'));
  assert.deepEqual(after.folders,before.folders);
}));

if (scenario === 'S1') {
  let listNotes;
  try {({listNotes} = await import(pathToFileURL(path.join(candidate,'src/queries.mjs'))));}
  catch(error) {listNotes = () => {throw error;};}
  const notes = [
    portable('b',{folderId:'garden',title:'BASIL Light',body:'East window',tags:['Plants'],updatedAt:'2026-09-07T10:00:00.000Z'}),
    portable('a',{folderId:'studio',title:'A lamp',body:'Quiet corner',tags:['Light'],updatedAt:'2026-09-07T10:00:00.000Z'}),
    portable('c',{folderId:'garden',title:'Basil plans',body:'Late spring',tags:['Seeds'],archived:true,updatedAt:'2026-09-08T10:00:00.000Z'}),
    portable('d',{folderId:'inbox',title:'Literal [x].*',body:'Marks only',tags:[],updatedAt:'2026-09-05T10:00:00.000Z'})
  ];
  const ids = options => listNotes(structuredClone(notes),options).map(n=>n.id);
  await check('F1','Folder AND search exclude unrelated matches',()=>assert.deepEqual(ids({folderId:'garden',query:'lamp'}),[]));
  await check('F2','Search without folder still filters',()=>assert.deepEqual(ids({query:'lamp'}),['a']));
  await check('F3','All words match case-insensitively across fields',()=>assert.deepEqual(ids({query:'  BASIL\t east  PLANTS '}),['b']));
  await check('F4','One missing word excludes a note',()=>assert.deepEqual(ids({query:'basil absent'}),[]));
  await check('F5','Archive inclusion preserves folder and search restrictions',()=>assert.deepEqual(ids({folderId:'garden',query:'basil',includeArchived:true}),['c','b']));
  await check('F6','Unknown folder returns no notes',()=>assert.deepEqual(ids({folderId:'missing',query:'lamp',includeArchived:true}),[]));
  await check('F7','Blank query and timestamp ties sort by ID',()=>assert.deepEqual(ids({query:' \t '}),['a','b','d']));
  await check('F8','Punctuation is literal',()=>assert.deepEqual(ids({query:'[x].*'}),['d']));
  await check('F9','Inputs and note objects are not mutated',()=>{
    const input = structuredClone(notes); const before = structuredClone(input);
    input.forEach(n=>{Object.freeze(n.tags);Object.freeze(n);}); Object.freeze(input);
    listNotes(input,{query:'basil',includeArchived:true}); assert.deepEqual(input,before);
  });
  await check('F10','Empty input returns an empty result',()=>assert.deepEqual(listNotes([],{query:'x'}),[]));
  await check('F11','HTTP query uses the same combined semantics without persisting changes',()=>withServer(async server=>{
    const before = await state(server);
    assert.deepEqual(ok(await server.request('/api/notes?folderId=garden&q=lamp')).notes,[]);
    assert.deepEqual(ok(await server.request('/api/notes?q=small%20tools')).notes.map(n=>n.id),['n4']);
    assert.deepEqual(ok(await server.request('/api/notes?folderId=garden&q=basil&includeArchived=true')).notes.map(n=>n.id),['n3']);
    assert.deepEqual(await state(server),before);
  }));
}
if (scenario === 'S2') {
  await check('I1','Valid import adds new records and persists across restart',()=>withServer(async(server,restart)=>{
    const before = await state(server); const incoming=[portable('p1'),portable('p2',{archived:true})];
    assert.deepEqual(ok(await post(server,'/api/import',bundle(incoming))),{imported:2,skipped:0});
    server=await restart();const after=await state(server);
    assert.deepEqual(after.notes.filter(n=>before.notes.some(b=>b.id===n.id)),before.notes);
    assert.deepEqual(after.notes.filter(n=>n.id.startsWith('p')).sort((a,b)=>a.id.localeCompare(b.id)),incoming);
    assert.deepEqual(after.folders,before.folders);
  }));
  await check('I2','Existing IDs are skipped without overwriting',()=>withServer(async server=>{
    const before=await state(server);
    assert.deepEqual(ok(await post(server,'/api/import',bundle([portable('n1'),portable('p1')]))),{imported:1,skipped:1});
    const after=await state(server);assert.deepEqual(after.notes.find(n=>n.id==='n1'),before.notes.find(n=>n.id==='n1'));
  }));
  await check('I3','Reimport is idempotent',()=>withServer(async server=>{
    const body=bundle([portable('p1')]);ok(await post(server,'/api/import',body));const before=await state(server);
    assert.deepEqual(ok(await post(server,'/api/import',body)),{imported:0,skipped:1});assert.deepEqual(await state(server),before);
  }));
  await check('I4','Invalid later entry cannot partially import valid earlier entries',()=>withServer(async server=>{
    const before=await state(server);errorResponse(await post(server,'/api/import',bundle([portable('p1'),portable('p2',{folderId:'absent'})])),400);assert.deepEqual(await state(server),before);
  }));
  await check('I5','Duplicate incoming IDs are rejected atomically',()=>withServer(async server=>{
    const before=await state(server);errorResponse(await post(server,'/api/import',bundle([portable('p1'),portable('p1')])),400);assert.deepEqual(await state(server),before);
  }));
  await check('I6','Schema and every required field are validated without coercion',()=>withServer(async server=>{
    const before=await state(server);
    const invalid=[null,{}, {version:'1',notes:[]},{version:2,notes:[]},{version:1,notes:{}},bundle([null])];
    for(const field of ['id','folderId','title','body','tags','archived','updatedAt']) {const n=portable('bad');delete n[field];invalid.push(bundle([n]));}
    for(const extra of [{id:' '},{id:1},{folderId:1},{title:' '},{body:1},{tags:['ok',1]},{tags:'tag'},{archived:'false'},{updatedAt:123}]) invalid.push(bundle([portable('bad',extra)]));
    for(const body of invalid) {errorResponse(await post(server,'/api/import',body),400);assert.deepEqual(await state(server),before);}
  }));
  await check('I7','Invalid dates and noncanonical timestamps are rejected',()=>withServer(async server=>{
    const before=await state(server);
    for(const updatedAt of ['not-a-date','2026-02-30T10:00:00.000Z','2026-09-07','2026-09-07T10:00:00Z','2026-09-07T10:00:00.000+00:00']) errorResponse(await post(server,'/api/import',bundle([portable('p1',{updatedAt})])),400);
    assert.deepEqual(await state(server),before);
  }));
  await check('I8','Skipped existing IDs are still validated',()=>withServer(async server=>{
    const before=await state(server);errorResponse(await post(server,'/api/import',bundle([portable('n1',{title:''})])),400);assert.deepEqual(await state(server),before);
  }));
  await check('I9','Empty import is a no-op; 500 accepted and 501 rejected',()=>withServer(async server=>{
    const before=await state(server);assert.deepEqual(ok(await post(server,'/api/import',bundle([]))),{imported:0,skipped:0});assert.deepEqual(await state(server),before);
    errorResponse(await post(server,'/api/import',bundle(Array.from({length:501},(_,i)=>portable(`limit-${i}`)))),400);assert.deepEqual(await state(server),before);
    assert.deepEqual(ok(await post(server,'/api/import',bundle(Array.from({length:500},(_,i)=>portable(`limit-${i}`))))),{imported:500,skipped:0});
  }));
  await check('I10','Malformed JSON returns a useful 400 without changing state',()=>withServer(async server=>{
    const before=await state(server);errorResponse(await server.request('/api/import',{method:'POST',raw:'{broken'}),400);assert.deepEqual(await state(server),before);
  }));
  await check('I11','Concurrent overlapping imports neither duplicate nor lose records',()=>withServer(async server=>{
    const responses=await Promise.all([post(server,'/api/import',bundle([portable('p1'),portable('p2')])),post(server,'/api/import',bundle([portable('p2'),portable('p3')]))]);
    const counts=responses.map(r=>ok(r));assert.equal(counts.reduce((n,c)=>n+c.imported,0),3);assert.equal(counts.reduce((n,c)=>n+c.skipped,0),1);
    const data=await state(server);for(const id of ['p1','p2','p3'])assert.equal(data.notes.filter(n=>n.id===id).length,1);
  }));
}
if(scenario==='S3') {
  const archive=async(server,id)=>ok(await post(server,`/api/notes/${id}/archive`,{}));
  const undo=(server,token)=>post(server,'/api/archive/undo',{token});
  const tokenOf=result=>{assert.equal(typeof result.undoToken,'string');assert.ok(result.undoToken.length>0);return result.undoToken;};
  await check('U1','Archive returns a token with a ten-second window',()=>withServer(async server=>{
    const start=Date.now();const result=await archive(server,'n1');tokenOf(result);assert.equal(result.note.archived,true);
    assert.match(result.expiresAt,/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
    const expiry=Date.parse(result.expiresAt);assert.ok(expiry>=start+9900 && expiry<=Date.now()+10100,'Expiry must be ten seconds after archive');
  }));
  await check('U2','Undo restores the exact original note and persists',()=>withServer(async(server,restart)=>{
    const before=await state(server);const result=await archive(server,'n1');const note=ok(await undo(server,tokenOf(result))).note;
    assert.deepEqual(note,before.notes.find(n=>n.id==='n1'));server=await restart();assert.deepEqual((await state(server)).notes,before.notes);
  }));
  await check('U3','State exposes pending undo for refresh and clears after success',()=>withServer(async server=>{
    assert.equal((await state(server)).pendingUndo,null);
    const result=await archive(server,'n1');const token=tokenOf(result);
    assert.deepEqual((await state(server)).pendingUndo,{token,noteId:'n1',expiresAt:result.expiresAt});
    ok(await undo(server,token));assert.equal((await state(server)).pendingUndo,null);
  }));
  await check('U4','Only latest successful new archive remains undoable',()=>withServer(async server=>{
    const first=tokenOf(await archive(server,'n1'));const second=tokenOf(await archive(server,'n2'));assert.notEqual(first,second);
    const before=await state(server);errorResponse(await undo(server,first),409);assert.deepEqual(await state(server),before);
    ok(await undo(server,second));const data=await state(server);assert.equal(data.notes.find(n=>n.id==='n1').archived,true);assert.equal(data.notes.find(n=>n.id==='n2').archived,false);
  }));
  await check('U5','Consumed or unknown tokens cannot change state',()=>withServer(async server=>{
    const token=tokenOf(await archive(server,'n1'));ok(await undo(server,token));const before=await state(server);
    errorResponse(await undo(server,token),409);errorResponse(await undo(server,'not-a-token'),409);assert.deepEqual(await state(server),before);
  }));
  await check('U6','Rejected archives preserve an existing undo',()=>withServer(async server=>{
    const result=await archive(server,'n1');const token=tokenOf(result);
    errorResponse(await post(server,'/api/notes/absent/archive',{}),404);errorResponse(await post(server,'/api/notes/n1/archive',{}),409);
    assert.equal((await state(server)).pendingUndo.token,token);ok(await undo(server,token));
  }));
  await check('U7','Server rejects expired undo and clears pending state',()=>withServer(async server=>{
    const result=await archive(server,'n1');const token=tokenOf(result);const delay=Date.parse(result.expiresAt)-Date.now();
    assert.ok(delay>9000 && delay<=10100,'Expected ten-second expiry');await sleep(delay+100);
    const before=(await state(server)).notes;errorResponse(await undo(server,token),409);const after=await state(server);assert.deepEqual(after.notes,before);assert.equal(after.pendingUndo,null);
  }));
  await check('U8','Archiving preserves all other note fields and malformed undo is 400',()=>withServer(async server=>{
    const before=await state(server);await archive(server,'n1');const after=await state(server);
    assert.deepEqual(after.notes,before.notes.map(n=>n.id==='n1'?{...n,archived:true}:n));
    errorResponse(await server.request('/api/archive/undo',{method:'POST',raw:'{bad'}),400);
    assert.deepEqual((await state(server)).notes,after.notes);
  }));
}
fs.writeFileSync(output,JSON.stringify({scenario,checks:results,passed:results.filter(r=>r.status==='pass').length,total:results.length,allPassed:results.every(r=>r.status==='pass')},null,2));
console.log(`${scenario}: ${results.filter(r=>r.status==='pass').length}/${results.length} acceptance checks passed`);
process.exitCode=results.every(r=>r.status==='pass')?0:1;
