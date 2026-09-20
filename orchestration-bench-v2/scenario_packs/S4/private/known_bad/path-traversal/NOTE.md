# path-traversal — adversarial

**Intended failure: A1 (and therefore every downstream check, because nothing is executed).**

This fixture is not a wrong audit. It is review finding F2, carried out against this pack's own
grader: the reference findings, with one `reproduction.module` replaced by
`"../../../../../../tmp/ob2-s4-payload/evil"`.

The v1 grader built the module path with `path.join(MODULES, `${name}.mjs`)` and imported the
result, so this string walked out of the frozen modules directory and executed an arbitrary
`.mjs` file of the submitter's choosing inside the grader process.

`reproduction.module` is now checked against the exact list of module basenames read from
`participant/src`, and the resolved path must sit directly inside that directory. A name that
is not on the list is a schema error — the finding points at a module that does not exist,
which is decidable without importing anything — so A1 fails, nothing is executed, and the
grader names both the offending value and the twelve names that are allowed.
