export const initialState = () => ({
  version: 1,
  folders: [{id: 'inbox', name: 'Inbox'}, {id: 'garden', name: 'Garden'}, {id: 'studio', name: 'Studio'}],
  notes: [
    {id: 'n1', folderId: 'garden', title: 'Morning light', body: 'Move the seedlings toward the east window.', tags: ['Plants'], archived: false, updatedAt: '2026-09-01T09:00:00.000Z'},
    {id: 'n2', folderId: 'studio', title: 'A quieter workspace', body: 'Try a small lamp beside the reading chair.', tags: ['Space'], archived: false, updatedAt: '2026-09-02T09:00:00.000Z'},
    {id: 'n3', folderId: 'garden', title: 'Seed catalogue', body: 'Order basil and rosemary for next spring.', tags: ['Plants', 'Later'], archived: true, updatedAt: '2026-09-03T09:00:00.000Z'},
    {id: 'n4', folderId: 'inbox', title: 'An unfinished thought', body: 'Small tools should leave room to think.', tags: ['Ideas'], archived: false, updatedAt: '2026-09-04T09:00:00.000Z'}
  ]
});
