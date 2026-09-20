import fs from 'node:fs';
import path from 'node:path';
import {initialState} from './seed.mjs';

export function createStore(filename) {
  fs.mkdirSync(path.dirname(filename), {recursive: true});
  let state = fs.existsSync(filename) ? JSON.parse(fs.readFileSync(filename, 'utf8')) : initialState();
  const save = next => {
    const temp = `${filename}.tmp`;
    fs.writeFileSync(temp, JSON.stringify(next, null, 2));
    fs.renameSync(temp, filename);
    state = next;
  };
  if (!fs.existsSync(filename)) save(state);
  return {
    read: () => structuredClone(state),
    update(fn) { const next = structuredClone(state); const result = fn(next); save(next); return result; }
  };
}
