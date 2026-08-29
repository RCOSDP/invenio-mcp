# Security

## Reporting

Please report suspected vulnerabilities through **GitHub's private vulnerability
reporting** on this repository (Security → Report a vulnerability), not as a public
issue.

Include what you did, what happened, and what you expected. A proof of concept helps
but is not required. **Do not include a working token** — the description of where it
leaked is what we need.

## What we consider serious here

This server stands between a language model and a repository holding published research
records. That shapes the severity of a report:

- **Anything that lets a token reach InvenioRDM without having been exchanged**, in
  keycloak mode. The received token is addressed to this server; forwarding it is the
  confused-deputy problem the MCP specification forbids, and it hands a downstream
  service credentials it was never meant to hold.
- **Anything that accepts a token minted for a different audience.** `aud` is checked
  against this server's own canonical URI precisely so that a token obtained for
  somewhere else cannot be walked in.
- **Anything that performs a write, a withdrawal or a restore without the scope for
  it** — including through `/mcp-auth`, which shares the tools but not the entrance.
- **Anything that puts a token into a log line, an error message, or a tool result.**
  The audit log carries `sub`, `azp` and `scope` deliberately, and never the token.
- **Anything that makes the server fetch a URL on request** beyond
  `upload_file_from_url`, which is SSRF-shaped and is why InvenioRDM v14 restricts
  transfer type `F` to system processes in the first place.

## Known operational hazards

These are documented rather than fixed, because they are properties of a configuration
rather than defects:

- **PAT mode has no audience separation.** That follows structurally from the token
  being an InvenioRDM token: there is nothing to exchange it into. It also means the
  server holds a credential that works directly against the repository. Use keycloak
  mode where that matters.
- **`MCP_TLS_INSECURE=1` disables certificate verification** for both InvenioRDM and
  Keycloak. It exists for self-signed development instances. The supported way is to
  append your CA to the system bundle instead.
- **`--allow-http` in `mcp-remote` sends the token in the clear.** Only over a trusted
  path.
- **The compose stack reads secrets from `.env` in the clear.** It is a starting point,
  not a deployment.

## Scope

The final permission decision is InvenioRDM's. A report that amounts to "an admin token
can delete records" describes InvenioRDM working as designed, not a vulnerability here.
