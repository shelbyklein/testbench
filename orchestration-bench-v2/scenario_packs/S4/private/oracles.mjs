// Correct implementations of the exports that carry a seeded defect.
//
// Defect identity is decided by disagreement: a finding's reproduction is executed against
// the shipped module and against the oracle for the same (module, export). If the two agree,
// the call demonstrates nothing and the finding is a false positive, whatever it claims.
// If they disagree, the call demonstrates exactly the defect seeded in that export.
//
// Keys are `<module>.<export>`. Every key must correspond to one defect in inventory.json.

const oracles = {
  'tags.normalizeTags'(input) {
    if (input === null || input === undefined) return [];
    const raw = Array.isArray(input) ? input : String(input).split(',');
    const seen = new Set();
    const out = [];
    for (const item of raw) {
      const lowered = String(item).trim().toLowerCase();
      if (!lowered) continue;
      if (seen.has(lowered)) continue;
      seen.add(lowered);
      out.push(lowered);
    }
    return out.sort();
  },

  'search.matchesQuery'(note, query) {
    const terms = String(query ?? '').trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (terms.length === 0) return true;
    const haystack = `${note?.title ?? ''} ${note?.body ?? ''}`.toLowerCase();
    return terms.every((term) => haystack.includes(term));
  },

  'dates.isOverdue'(dueISO, nowISO) {
    const due = new Date(dueISO).getTime();
    const now = new Date(nowISO).getTime();
    if (Number.isNaN(due) || Number.isNaN(now)) return false;
    return now > due;
  },

  'sorting.sortNotes'(notes) {
    const copy = [...(notes ?? [])];
    const stamp = (note) => {
      const value = new Date(note?.updatedAt).getTime();
      return Number.isNaN(value) ? -Infinity : value;
    };
    copy.sort((a, b) => {
      const delta = stamp(b) - stamp(a);
      if (delta !== 0) return delta;
      const left = String(a?.title ?? '').toLowerCase();
      const right = String(b?.title ?? '').toLowerCase();
      if (left === right) return 0;
      return left < right ? -1 : 1;
    });
    return copy;
  },

  'importParse.parseImport'(text) {
    const out = [];
    for (const line of String(text ?? '').split('\n')) {
      if (!line.trim()) continue;
      const fields = line.split('|').map((field) => field.trim());
      const title = fields[0] ?? '';
      if (!title) continue;
      out.push({
        title,
        body: fields[1] ?? '',
        tags: (fields[2] ?? '').split(',').map((t) => t.trim()).filter(Boolean),
      });
    }
    return out;
  },

  'pagination.paginate'(items, page, perPage) {
    const list = items ?? [];
    const size = Math.max(1, Math.trunc(perPage ?? 1));
    const current = Math.max(1, Math.trunc(page ?? 1));
    const total = list.length;
    const totalPages = Math.max(1, Math.ceil(total / size));
    const start = (current - 1) * size;
    return { items: list.slice(start, start + size), page: current, perPage: size, total, totalPages };
  },
};

export function oracleFor(module, exportName) {
  return oracles[`${module}.${exportName}`] ?? null;
}

export function oracleKeys() {
  return Object.keys(oracles).sort();
}
