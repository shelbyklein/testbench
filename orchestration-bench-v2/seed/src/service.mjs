import {listNotes} from './queries.mjs';

export function createService(store) {
  return {
    state: () => store.read(),
    list: options => listNotes(store.read().notes, options),
    archive(id) {
      return store.update(state => {
        const note = state.notes.find(n => n.id === id);
        if (!note) { const error = new Error('Note not found'); error.status = 404; throw error; }
        note.archived = true;
        return {note};
      });
    }
  };
}
