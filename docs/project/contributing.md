# Contributing

Issues and pull requests are welcome, including "the documentation is wrong here" —
that is a defect like any other.

## Getting set up

There is nothing to build. The servers are two Python files.

```bash
git clone https://github.com/RCOSDP/invenio-mcp
cd invenio-mcp
pip install "mcp==1.26.0" "pyjwt[crypto]>=2.8" "httpx>=0.27" "uvicorn>=0.30"
```

The stdio server needs only `mcp`; the rest is for the HTTP one.

```bash
# The documentation site
pip install -r docs/requirements.txt
mkdocs serve            # English at /, Japanese at /ja/
```

## What CI checks

Run these before opening a pull request — they are exactly what
`.github/workflows/ci.yml` does:

```bash
python3 -m py_compile http/mcp_server.py stdio/server.py
python3 tools/gen_tool_reference.py --check    # the docs match the code
mkdocs build --strict                          # no broken links
```

CI additionally loads both servers and asserts the tool counts (12 and 33), that every
tool has a description, that `en.json` and `ja.json` carry the same keys, and that both
servers report the same `__version__`.

## Testing against a real instance

There is no test suite that runs without InvenioRDM, and pretending otherwise would be
worse than saying so. What exists runs against a live one:

```bash
python3 stdio/server.py --selftest                # create → publish → delete → restore
python3 http/conformance/mcp_client.py            # the authorization spec, PASS/FAIL
python3 http/conformance/verify-mcp-files.py      # all three file transfer paths
bash    http/conformance/curl-tour.sh             # the flow, in curl
```

**Use a demo instance with disposable data.** `--selftest` soft-deletes its record at
the end, which leaves a tombstone behind.

Say in the pull request which of these you ran, and against what.

## What a review will ask

1. **Is the user-facing string in `locales/`?** Anything a person or a model reads —
   tool descriptions, errors, the startup banner — belongs there, in **both** languages.
   Code comments stay where they are; they are for developers. See
   [Languages](../reference/languages.md).
2. **Is the reasoning in the code?** Comments explain *why*. What the line does is
   already visible. Most of the comments in these files record something that was
   actually hit — a client that only authorizes after a 401, a transfer type an ordinary
   user cannot use — and those are the ones worth keeping.
3. **Does the permission decision still end at InvenioRDM?** The MCP scopes separate
   what a client may *ask for*. They are not a second permission system, and a change
   that starts deciding here instead will be sent back.
4. **Would this change what a model sees?** Renaming a tool or an argument, or removing
   one, is a breaking change even when nothing fails to compile. So is rewording a
   description in a way that drops a warning. See [Versioning](versioning.md).

## Adding a tool

- Add the function with `@mcp.tool(description=t("tools.<name>"))` — **no docstring**,
  since the description comes from the locale files.
- Add the text to `locales/en.json` **and** `locales/ja.json`.
- Add its scope to `TOOL_SCOPES`. `None` means "callable unauthenticated", which is
  right only for public read operations.
- Put it in a group in `tools/gen_tool_reference.py`. The generator fails if a tool is
  not assigned to one, which is deliberate — an uncategorised tool would silently vanish
  from the reference.
- Re-run `python3 tools/gen_tool_reference.py`.
- Update the tool counts if they changed: the READMEs, `docs/index.md`, and the
  assertion in `.github/workflows/ci.yml`.

## Adding a language

Copy `locales/en.json`, translate, and save it as `<tag>.json` next to it. Nothing has
to be registered — the server discovers what is in the directory. Missing keys fall back
to English, so a partial translation is fine to submit.

## Writing documentation

Every page has a `.md` and a `.ja.md`. **Both, in the same pull request.** A page that
exists in one language only is worse than one that does not exist, because the language
switcher then leads somewhere that is not there.

The [tool reference](../reference/tools.md) is generated. Edit the locale files instead.

## Commit messages

`type: summary`, in the imperative, in either language — the history uses both.
`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`.
