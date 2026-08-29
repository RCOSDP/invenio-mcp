# Contributing

Full guide: **<https://rcosdp.github.io/invenio-mcp/project/contributing/>**
（日本語: <https://rcosdp.github.io/invenio-mcp/ja/project/contributing/>）

```bash
# Both servers, both languages, and the generated reference
python3 -m py_compile http/mcp_server.py stdio/server.py
python3 tools/gen_tool_reference.py --check

# The documentation site
pip install -r docs/requirements.txt
mkdocs serve            # English at /, Japanese at /ja/
```

There is no test suite that runs without an InvenioRDM instance, and pretending
otherwise would be worse than saying so. What exists instead runs against a live one:

```bash
python3 stdio/server.py --selftest                    # create → publish → delete → restore
python3 http/conformance/mcp_client.py                # the authorization spec, PASS/FAIL
python3 http/conformance/verify-mcp-files.py          # all three file transfer paths
```

Four things a review will ask:

1. **Is the user-facing string in `locales/`?** Anything a person or a model reads —
   tool descriptions, errors, the banner — belongs there in **both** languages, not in
   the code. Comments in the code stay as they are; they are for developers.
2. **Is the reasoning in the code?** Comments explain *why*. What the line does is
   already visible.
3. **Does the permission decision still end at InvenioRDM?** The MCP scopes separate
   what a client may *ask for*. They are not a second permission system, and a change
   that starts deciding here instead will be sent back.
4. **Would this change what a model sees?** Renaming a tool or an argument, or removing
   one, is a breaking change even when nothing fails to compile. See
   [versioning](https://rcosdp.github.io/invenio-mcp/project/versioning/).

Issues and pull requests are welcome, including "the documentation is wrong here" —
that is a defect like any other.
