# known_bad: data-loss

The migration is complete in shape but `loadNotes` quietly drops any saved record without a folder, so one of the five stored notes disappears on the first read and is gone from the next save. Intended failure: preservation of the saved records.
