// Shared persistence layer, note record v2.
import fs from 'node:fs';

export const SCHEMA_VERSION = 2;

export function normalizeTags(input) {
  const raw = Array.isArray(input) ? input : String(input ?? '').split(',');
  const seen = new Set();
  for (const item of raw) {
    const tag = String(item).trim().toLowerCase();
    if (tag) seen.add(tag);
  }
  return [...seen].sort();
}

export function normalizeTimestamp(value) {
  const text = String(value ?? '').trim();
  if (!text) return null;
  const iso = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text) ? `${text.replace(' ', 'T')}Z` : text;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) throw new Error(`unparseable timestamp: ${text}`);
  return date.toISOString();
}

export function migrateRecord(record) {
  if (record === null || typeof record !== 'object') throw new Error('record must be an object');
  if (record.schemaVersion === SCHEMA_VERSION) {
    // Already v2: idempotent, but still normalised so a second pass is a true no-op.
    return {
      id: record.id,
      title: record.title,
      body: record.body ?? '',
      tags: normalizeTags(record.tags),
      createdAt: normalizeTimestamp(record.createdAt),
      folder: record.folder ?? null,
    };
  }
  if (record.schemaVersion !== undefined && record.schemaVersion !== 1) {
    throw new Error(`unsupported record schemaVersion: ${record.schemaVersion}`);
  }
  return {
    id: record.id,
    title: record.title,
    body: record.body ?? '',
    tags: normalizeTags(record.tags),
    createdAt: normalizeTimestamp(record.createdAt ?? record.created),
    folder: record.folder ?? null,
  };
}

export function requireV2(note, where) {
  if (note === null || typeof note !== 'object' || note.schemaVersion !== SCHEMA_VERSION) {
    throw new Error(`${where} needs a v2 record (schemaVersion ${SCHEMA_VERSION}); got ` +
                    `schemaVersion ${JSON.stringify(note?.schemaVersion ?? null)}`);
  }
  return note;
}

export function loadNotes(file) {
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  const envelope = Array.isArray(raw) ? { schemaVersion: 1, notes: raw } : raw;
  const notes = envelope?.notes;
  if (!Array.isArray(notes)) throw new Error('notes file is malformed');
  const version = envelope.schemaVersion ?? 1;
  if (typeof version !== 'number' || version > SCHEMA_VERSION) {
    throw new Error(`unsupported file schemaVersion: ${version}`);
  }
  return notes.map(migrateRecord);
}

export function saveNotes(file, notes) {
  const migrated = (notes ?? []).map(migrateRecord);
  fs.writeFileSync(file, `${JSON.stringify({ schemaVersion: SCHEMA_VERSION, notes: migrated }, null, 2)}\n`);
  return migrated.length;
}
