# Commit convention

How commit messages are written in this repository. `git log` shows it in
practice.

The subject line is strict: a verb from a closed set and a bare noun phrase.
The body is optional and looser.

## Subject line

```
<Verb> <object>[ <qualifier>]
```

### 1. Start with a verb from the closed set

Reach for these first:

| Verb | Use for |
|---|---|
| `Add` | A new file, feature, capability or test. The default. |
| `Update` | A change to something that already exists and still does the same job. |
| `Fix` | Correcting a defect. |
| `Remove` | Deleting a file, feature or dead path. |

Only when those would be imprecise: `Move`, `Rewrite`, `Split`, `Trim`,
`Port`, `Implement`, `Optimise`, `Ignore`.

Anything else is out. Do not open a subject with a verb for what the program
now does (`Keep`, `Stop`, `Report`, `Warn`, `Match` and the like). The subject
says what the commit did to the tree; the behaviour goes in the body.

`Initial commit` is allowed for a root commit only.

### 2. No article straight after the verb

The object is a bare noun phrase:

```
Add test suite                      not  Add a test suite
Trim module docstring               not  Trim the module docstring
Remove superseded shell scripts     not  Remove the superseded shell scripts
```

An article deeper in the line, inside a phrase, is fine where dropping it
would read like a telegram: `Fix taps landing mirrored when the phone is
turned the other way`.

### 3. Form

- Imperative mood: `Add`, never `Added` or `Adds`.
- Capitalise the first word only, unless a later word is an identifier or a
  proper noun.
- No trailing full stop, no `type:` prefix.
- 60 characters at most.
- Name files and symbols literally when the change is about one:
  `Add canvas_download.py`.
- `and` joining two items is fine. Three or more means the commit should
  probably be split.
- Never a bare `Update README.md`. Say what changed.

## Body

Optional. Add one only when there is something the diff cannot tell a reader:
a reason, a constraint, a number, a consequence.

- One blank line after the subject.
- Every line is a `- ` bullet, one line each, never wrapped, 76 characters at
  most, no trailing full stop.
- One to three bullets; up to six for a large feature.
- State the fact; do not narrate what was wrong.

```
Fix dual-band device double counting

- A dual-band device fingerprints twice, inflating counts by 12-39%
- Scope macs-seen to the window rather than every address ever used
```

## Spelling

British throughout: `optimise`, `behaviour`, `licence`, `summarise`.

## Checklist

1. Does the subject start with `Add`, `Update`, `Fix` or `Remove`, or a
   justified secondary verb?
2. Is the word straight after the verb an article? Delete it.
3. Under 60 characters, no full stop, imperative?
4. If there is a body, does every bullet fit on one line?
5. Does the body say something the diff does not?
6. British spelling? ASCII only?
