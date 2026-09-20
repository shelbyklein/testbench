// Public contract: listNotes(notes, {folderId?, query?, includeArchived?}) -> notes[]
// Search words should all occur in the combined title/body/tags text.
export function listNotes(notes, {folderId = '', query = '', includeArchived = false} = {}) {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return notes.filter(note => {
    const folderMatches = !folderId || note.folderId === folderId;
    const haystack = `${note.title} ${note.body} ${note.tags.join(' ')}`.toLocaleLowerCase();
    const searchMatches = words.every(word => haystack.includes(word));
    // Reported bug: combining a folder and a search leaks unrelated notes.
    return (folderMatches || (words.length > 0 && searchMatches)) && (includeArchived || !note.archived);
  }).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt) || a.id.localeCompare(b.id));
}
