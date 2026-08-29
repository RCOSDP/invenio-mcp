# Versioning

invenio-mcp follows [Semantic Versioning 2.0.0](https://semver.org/):
`MAJOR.MINOR.PATCH`. Both servers carry the **same** version — `__version__` in
`http/mcp_server.py` and `stdio/server.py`, checked by CI to agree, and reported to
clients as `serverInfo.version`.

The version is still `0.x` — see [Before 1.0](#before-10). **The current release is not
written on this page**, because it would go stale at every release; it is in the
[changelog](changelog.md).

```bash
python3 stdio/server.py --version      # invenio-mcp stdio server <version>
# the HTTP server prints it in the startup banner
```

## What the version covers

SemVer is only meaningful once you say what the public surface is. Here the consumer is
usually **a language model reading tool descriptions**, not a compiler reading
signatures, and that changes what "breaking" means.

| Part of the contract | Example of a breaking change |
| --- | --- |
| **Tool names** | A tool is removed or renamed. The model's stored habits and the user's saved prompts both break |
| **Tool arguments** | An argument is removed or renamed; a required one is added; a default changes in a way that alters behaviour |
| **Return shape** | A key disappears from a result, or changes type |
| **Scopes** | A tool starts requiring a scope it did not; a scope is renamed. Existing tokens stop working |
| **Endpoints** | `/mcp` or `/mcp-auth` moves; the canonical URI is derived differently |
| **Environment variables** | A setting is renamed or removed; a default changes behaviour |
| **Language resource keys** | A key referenced by the code disappears — a translation that was complete silently becomes partial |

Not covered: the wording of a description or an error message (those are expected to
improve), log line contents, internal module layout, and the conformance scripts.

### A description is not a signature, and it still matters

Rewording a tool description is a **patch**. It is also the single most effective way to
change how the whole thing behaves, because that text is the interface the model reads.
A reword that removes a warning — "files cannot be added to a published record", "this
needs `confirm=True`" — is not cosmetic and belongs in the changelog even though nothing
in the schema moved.

### Loosening a refusal is major

Some of what these servers do is refusing:

- `delete_record` does nothing without `confirm=True`
- withdrawal is a **soft** delete; a hard purge is not offered
- reading public records is unauthenticated, but writing is never
- the received token is **exchanged**, never forwarded to InvenioRDM
- `aud` is validated against this server's own canonical URI

Weakening any of those is a **major** change even if no name moves, because the damage
would be to a repository's records rather than to a build.

## Both servers, one version

They are released together. Bumping only one would leave "invenio-mcp 0.2.0" meaning
two different things depending on which file you looked at. CI fails when the two
`__version__` values disagree, and the release workflow fails when the tag does not
match them.

## What is not versioned here

**InvenioRDM's own API.** These servers target InvenioRDM v14. If a future InvenioRDM
changes a REST behaviour we depend on, the fix ships as whatever severity the *user
visible* change warrants — a tool that stops working is major regardless of whose change
caused it.

**The MCP specification.** The HTTP server targets the 2026-07-28 authorization
specification. Following a newer one is a breaking change if it changes what clients
must do.

## Before 1.0

While the version starts with `0`, **the minor number carries breaking changes**:
`0.1.0 → 0.2.0` may break, `0.0.1 → 0.0.2` should not.

1.0 will be tagged when:

- the tool set has been stable across at least one InvenioRDM upgrade,
- the conformance checks pass against an instance someone else runs, and
- keycloak mode has been used in earnest, not only demonstrated.

Until then, pin an exact version.

## Releasing

```bash
# 1. Bump both servers and move [Unreleased] into the new version, in both languages
vim http/mcp_server.py stdio/server.py CHANGELOG.md CHANGELOG.ja.md

# 2. Check what CI will check
python3 tools/gen_tool_reference.py --check
mkdocs build --strict

# 3. Tag
git tag -a v0.0.3 -m "v0.0.3" && git push origin v0.0.3
```

The release workflow verifies that the tag matches `__version__` in **both** servers and
that both changelogs have a section for it, then builds the image and drafts the release
notes from `CHANGELOG.md`.
