# unknown-export — adversarial

**Intended failure: A3.**

The reference findings plus one extra finding whose `reproduction.export`
(`tags.normalizeTagsFast`) is not on the module's real export list.

The module name is legitimate, so this is not a traversal attempt; it is a finding that cannot
be demonstrated. The export is checked against the manifest the worker builds by importing the
frozen modules before it looks at any submission-controlled name, and a name that is not there
reproduces nothing. It therefore counts as a false positive: precision fails, and recall,
de-duplication and severity are untouched because the other six findings are genuine.
