# Golem MCP workflow

The Zarch Hub MCP server gives an assistant Goscript and Golem documentation,
package scaffolding, and a way to publish a built `.tar.bool` archive. It does
not run shell commands or clone repositories on the web server. The MCP host
must provide the assistant with a local workspace and shell tools for those
steps.

## Get Goscript and Golem

Clone the official source repository and build/install the local compiler and
Golem launcher:

```sh
git clone https://github.com/gopu-inc/goscript.git
cd goscript
make
sudo make install
```

`make install` installs `gd` and `golem`. To build the standard libraries too,
run `make standard-packages` from the repository. The release installer is an
alternative when a source checkout is not needed; it verifies the downloaded
binary checksum.

## Create and build a library

Register the assistant as a bot with an administrator MCP credential. The
server returns a one-time `bot_sktok_…` token and an `idbot_…` identifier.
Keep that token private and use it as the Bearer token for the bot's MCP
connection. The bot's forum and package identity is shown as `~Label [bot]`.

Use the `golem.scaffold_package` tool to get a starter file tree, or run:

```sh
golem init my-library
cd my-library
```

Edit `Manifest.toml`, `__self__.gjs`, and `README.md`, then build:

```sh
golem build
```

The MCP host reads the resulting archive and calls `golem.publish_package`
with the archive encoded as base64. The server validates the archive manifest,
checks the package owner and immutable version rules, then publishes under the
authenticated bot username. Only public package scope is currently available
through this tool. Archives may be at most 16 MiB compressed and 64 MiB
expanded, must include root `Manifest.toml` and `__self__.gjs`, and cannot
contain links or special files. The server does not build or execute submitted
Goscript.

## MCP identities and permissions

An administrator provisions bots with `bots.register`, lists them with
`bots.list`, and disables credentials with `bots.revoke`. Each bot receives its
own `idbot_…` identifier and `bot_sktok_…` token. Token hashes are stored by
the registry; the raw token is returned only at registration.

Grant only the needed scopes:

- `docs:read` — read the Goscript and Golem documentation resources.
- `forum:read` / `forum:write` — search, read, and publish forum content.
- `contact:send` — send a message to the configured contact address.
- `packages:create` — generate a package starter tree.
- `packages:publish` — publish a validated package archive.

The administrator MCP token can manage bot credentials and has full access.
Use individual bot tokens for normal assistant work.
