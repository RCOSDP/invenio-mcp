**What this changes, and why**

<!-- The reasoning matters more than the diff. A future reader wants to know what
     you knew that made this the right answer. -->

**Checks**

- [ ] `bash tools/check.sh` passes (say which checks reported `SKIP`, if any)
- [ ] User-facing strings are in `locales/`, in **both** `en.json` and `ja.json`
- [ ] `python3 tools/gen_tool_reference.py` was re-run if tools or their text changed
- [ ] Documentation is updated in both languages where the behaviour is described
- [ ] If a tool, argument or scope was renamed or removed, the changelog says so and
      [versioning](https://rcosdp.github.io/invenio-mcp/project/versioning/) was checked
- [ ] Exercised against a live InvenioRDM (say which check, and which version)
