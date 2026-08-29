# Languages

Everything a person or a model reads — tool descriptions, error messages, the startup
banner — comes from language resources. **English and Japanese ship by default.**

Comments in the code are a different matter: they are for developers and stay where
they are.

## Choosing one

| `MCP_LANG` | Result |
| --- | --- |
| `en` | English |
| `ja` | Japanese |
| unset | taken from the system locale (`LC_ALL`, `LC_MESSAGES`, `LANG`), English if that does not resolve |
| anything else | English — an explicit unknown tag does **not** fall back to the system locale |

Locales in the system's own form work too: `ja_JP.UTF-8`, `ja-JP` and `JA` all resolve
to `ja`. A regional resource is preferred when one exists, so `ja-jp.json` wins over
`ja.json` for `LANG=ja_JP.UTF-8`.

The startup banner prints what it resolved, and which languages it found:

```
  language (MCP_LANG)               : ja (available: en ja)
```

## Where the files are

```
http/locales/en.json     stdio/locales/en.json
http/locales/ja.json     stdio/locales/ja.json
```

Beside each server, so that copying a server means copying its text. `MCP_LOCALES_DIR`
moves them elsewhere.

The two servers have separate files because they have different tools and say different
things — the stdio descriptions are shorter and mention no scopes.

## The format

Nested keys, and a value that is either a string or an array of lines joined with
newlines. The array form is there so that a long description stays readable and
diffable in JSON.

```json
{
  "tools": {
    "publish_record": "Publish a draft (mcp:write).",
    "search_records": [
      "Search published records (**works unauthenticated**).",
      "",
      "With a token the search runs as that user, so their own drafts are included too."
    ]
  },
  "errors": {
    "file_exists": "'{filename}' already exists. Pass overwrite=True to replace it"
  }
}
```

`{name}` placeholders are filled in with `str.format`. **Formatting only happens when
the call site passes arguments**, so braces inside a description — `resource_type{id}`,
a JSON example — are left alone.

## Adding a language

Copy `en.json`, translate, and drop it in as `<tag>.json`. The server discovers whatever
is in the directory; nothing has to be registered.

**Missing keys fall back to English**, so a partial translation runs correctly from the
first key you translate. A key missing from every file renders as the key name, which is
ugly on purpose — it is meant to be noticed.

CI checks that `en.json` and `ja.json` carry exactly the same keys, because a key
present in only one language still *works* (it silently falls back), which is precisely
why it would otherwise go unnoticed.

## One string stays English

`error_description` inside the `WWW-Authenticate` header. RFC 6750 permits only a
subset of ASCII there, so a translated string cannot go in it. The header carries the
English text; the JSON body of the same 401/403 response carries the translation:

```http
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer error="invalid_token", scope="mcp:write",
  resource_metadata="https://mcp.example.org/.well-known/oauth-protected-resource/mcp",
  error_description="tool 'create_record' requires authorization"

{"error": "invalid_token",
 "error_description": "ツール 'create_record' には認可が要る",
 "required_scope": "mcp:write"}
```

## The language is per process

MCP has no locale negotiation — `initialize` carries no locale field — so the server
cannot vary by client. To serve two languages, run two instances with different
`MCP_LANG` values.

For the stdio server this is less of a constraint than it sounds: the client launches
the process, so `MCP_LANG` in the client's `env` block is already per-user.

## What the model sees

The [tool reference](tools.md) on this site is generated from these same files, so the
English and Japanese pages show exactly the strings the servers hand to a client.
