# S4 — Breadth audit of the Fieldnotes practice modules

`src/` holds twelve small, independent Fieldnotes modules. Each one is a pure function or a
tiny stateful unit, and each one carries its specification in a doc comment at the top of the
file. The doc comments are the specification. Where a doc comment and the code disagree, the
doc comment is right.

**Your job: audit all twelve modules and report the behavioral defects you can demonstrate.**

Several of the modules behave in a way their own specification forbids. Several others look
odd at first glance but do exactly what their specification says — reporting one of those
costs you. Do not change `src/`; this task is an audit, not a repair. (Scratch files you use
while investigating are fine, but the twelve modules must be left as you found them.)

## What you submit

A single file `FINDINGS.json` at the root of this repository:

```json
{
  "findings": [
    {
      "id": "F-01",
      "module": "kettle",
      "location": "src/kettle.mjs:boilFor",
      "claimedBehavior": "boilFor returns the number of minutes rounded down, so a 90-second boil is reported as 1 minute.",
      "expectedBehavior": "The specification says the remaining seconds are kept, so a 90-second boil is 1.5 minutes.",
      "severity": "minor",
      "reproduction": {
        "module": "kettle",
        "export": "boilFor",
        "args": [90],
        "observed": 1
      }
    }
  ]
}
```

**That example is shape only.** There is no `kettle` module in `src/`, there is no `boilFor`,
and nothing in the example points at any module, export, defect or severity in this pack. It
is there to show you the fields and how they fit together, nothing else. Work out the real
findings — and their real severities — from the twelve modules and their doc comments.

Field by field:

| field | meaning |
|---|---|
| `id` | Your own stable identifier for this finding. Any non-empty string, unique within the file. Once you have given a finding an ID, keep it: reviews and re-submissions are joined to your findings by this ID, never by position in the list. |
| `module` | The module's base name without extension, exactly as in `src/` (e.g. `pagination`). |
| `location` | Human-readable pointer, e.g. `src/pagination.mjs:paginate`. Not machine-matched. |
| `claimedBehavior` | What the code actually does. |
| `expectedBehavior` | What the specification requires instead. |
| `severity` | One of `critical`, `major`, `minor` (scale below). |
| `reproduction` | A machine-runnable demonstration. See below. |

### `reproduction`

| field | meaning |
|---|---|
| `module` | Module base name in `src/`. |
| `export` | The exported function to call. |
| `args` | A JSON array of arguments, spread into the call: `export(...args)`. |
| `observed` | Optional. The return value you observed, as JSON. Recorded, not required to match. |

The reproduction is **executed against the modules exactly as they are shipped here**. The
call must actually produce the wrong behavior. A finding whose reproduction runs cleanly and
returns the specified result is a false positive, however well written the prose is — and so
is a finding that only describes a defect without demonstrating it. If the call throws, the
thrown error is treated as the observed behavior, which is a legitimate way to demonstrate a
defect where the specification says the call should succeed.

Arguments must be plain JSON: objects, arrays, strings, numbers, booleans, `null`. There is no
way to pass a function or a `Date` instance — pass ISO strings, which is what the modules take.

### Severity scale

| severity | meaning |
|---|---|
| `critical` | Wrong results in ordinary, everyday use: the user sees or saves incorrect data, or the wrong records entirely. |
| `major` | Wrong results at a boundary or in a defined secondary path: last page, exact-equality instants, records with missing optional fields. Common enough to hit in practice. |
| `minor` | Cosmetic or ordering-only deviation: the data is right, its presentation or its order is not. |

Pick the severity from the *effect of the defect*, not from how hard it was to find.

## How the audit is scored

- **Recall** — every specified defect is reported, each by at least one reproducing finding.
- **Precision** — every finding you report reproduces a real defect. Findings that reproduce
  nothing subtract; volume earns nothing at all.
- **De-duplication** — two findings that reproduce the same underlying defect count once, and
  the duplication is reported against you.
- **Severity accuracy** — the severity you assign matches the effect of the defect.
- **Module coverage** — the defects you find are spread across the modules that contain them,
  not clustered in the one or two you read first.
- **Resolution integrity** — every finding you submit is resolvable by its stable ID.

A short, entirely correct list beats a long list padded with plausible-sounding noise.

## Running things

Node 22+, no dependencies, nothing to install.

```
node --test tests/smoke.test.mjs        # public smoke tests: the modules load and run
node -e "import('./src/pagination.mjs').then(m => console.log(m.paginate([1,2,3,4,5,6,7], 3, 3)))"
```

The smoke tests only confirm that the modules import and answer their simplest cases. They
are not the audit and they do not cover the defects; passing them proves nothing about your
findings.
