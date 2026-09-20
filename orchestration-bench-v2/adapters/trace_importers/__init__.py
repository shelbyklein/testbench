"""Trace importers.

Each module exposes `NAME`, `VERSION`, `detect(path) -> bool` and
`parse(path, run_id, experiment_id) -> Iterable[event]` (contracts/CONTRACTS.md §8).
Detection validates structure; it never guesses from a file name.
"""
