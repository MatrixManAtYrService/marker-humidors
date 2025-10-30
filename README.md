# marker-humidors

Dry-erase markers usually get thrown away because they dry out, long before their ink runs out. That happens fastest in dry climates.

A **marker humidor** is a lidded plastic container with a layer of sponges in the bottom, soaked in isopropyl alcohol. Markers are stored on top of the sponges, not in the alcohol, and the sealed lid keeps the vapor in so they don't dry out. The idea is that people put markers back in the humidor after use, and the markers last much longer.

<p align="center">
  <img src="docs/humidors.jpg" alt="Two marker humidors on a desk: clear plastic containers with clip-on lids, a layer of sponges in the bottom, and dry-erase markers piled on top. The one on the left has a printed card taped to it explaining what a marker humidor is." width="640">
</p>

Whether a humidor really helps only becomes clear over months, so each one carries a QR code. It leads to a **feedback page** where people say how the humidor is doing. Their comments build up a record that future readers can use to decide whether it works, and whether to make more. Each humidor gets a printable sheet like this, with two cards to cut apart and tape to different sides of the box:

<p align="center">
  <img src="docs/example-sheet.png" alt="Example printable sheet for a humidor named Alejandro: a QR card reading 'humidor name: Alejandro', a QR code, 'scan to leave feedback', and below it, separated by a dashed cut line, a card explaining what a marker humidor is, how to use it, and that it will not restore markers that are already dry" width="260">
</p>

This repo provides `humidor`, a command-line tool that:

- **draws printable sheets like this one** for each humidor, with a QR code for its page and a message about how to use the box;
- **configures the feedback pages on [Unison Cloud](https://unison.cloud)**, one per humidor;
- **manages them afterwards:** reading and moderating comments, checking every page is up, rolling out changes, and retiring humidors.

Scanning the code opens that humidor's page:

<p align="center">
  <img src="docs/feedback-page.png" alt="A humidor's feedback page: the title Marker Humidor, 'name: Chucho', a paragraph asking for comments on whether the humidor improves marker lifetime, the question 'How is Chucho doing?' above a text box with a 0 / 2000 counter and a Post button, one earlier comment, and a 'Powered by unison.cloud and github:MatrixManAtYrService/marker-humidors' footer" width="480">
</p>

- **One page per humidor.** Pages are separate: each has its own comments. A humidor's name only identifies the box, so moving it to a different room needs no change.
- **No accounts.** Each browser tab gets a random identity, so people can edit or delete what they just wrote. Closing the tab gives that up for good.
- **Text only,** up to 2000 characters, with a counter.
- **You moderate:** you can edit or delete any comment by using the CLI (or directing an agent do so).

Once a page is deployed, Unison Cloud serves it by itself. Your computer, this repo and its server can all be off, and people can still read the page and leave comments.

## Contents

- [One-time setup](#one-time-setup)
- [Start the server](#start-the-server)
- [Add a humidor and print its cards](#add-a-humidor-and-print-its-cards)
- [Read the feedback](#read-the-feedback)
- [Clean up comments](#clean-up-comments)
- [Check that everything is working](#check-that-everything-is-working)
- [Update the pages](#update-the-pages)
- [Retire a humidor](#retire-a-humidor)
- [Manage from another machine, or replace a token](#manage-from-another-machine-or-replace-a-token)
- [Working with an AI agent](#working-with-an-ai-agent)
- [Command reference](#command-reference)
- [Troubleshooting](#troubleshooting)
- [How it works](#how-it-works)
- [Development](#development)

## One-time setup

1. **Fork and clone this repo.** Everything below runs from its root directory.

2. **Get the tools.** The easy way is [nix](https://nixos.org/download):

   ```bash
   nix develop      # a shell with ucm (Unison), Python and humidor on the PATH
   ```

   Without nix, install [uv](https://docs.astral.sh/uv/) and [ucm](https://www.unison-lang.org/docs/install-instructions/) 1.5 or later, then put `./uv_run.sh` in front of every `humidor` command below (e.g. `./uv_run.sh humidor ls`).

3. **Log in to Unison Cloud.** Create an account at [unison.cloud](https://unison.cloud), then:

   ```bash
   ucm              # at the ucm prompt, type:  auth.login   then quit with  exit
   ```

   This saves a login in `~/.local/share/unisonlanguage/credentials.json`. It controls your whole Unison Cloud account, so keep it private: `chmod 600` it.

4. **Point the page footer at your fork.** Every page ends with "Powered by unison.cloud and github:YOU/marker-humidors", linking to Unison Cloud and to your repo. Set your repo's link in `humidor.toml`:

   ```toml
   repo_url = "https://github.com/YOU/marker-humidors"
   ```

## Start the server

`humidor serve` is how you configure Unison Cloud. It deploys, updates and removes pages, and reads and moderates comments for you. It asks your permission before any change. The pages don't depend on it: they run on Unison Cloud whether or not the server is running.

So start it when you want to manage your humidors, in a terminal you can see:

```bash
humidor serve
```

When you're done, stop it with Ctrl-C. Every `humidor` command except `serve` needs it running, including reading comments.

The first run spends a minute or two downloading Unison libraries. In a second terminal, check the setup:

```bash
humidor check
```

Every entry in `setup` should say `"ok": true`. Anything that doesn't comes with a `fix`.

**Approving changes.** Commands that change something (create, deploy, delete, edit, rm) pause until you approve them in the server's terminal. The server shows what will change, then waits five minutes for you to type `yes`:

```
========================================================================
humidor: approval requested for CREATE
------------------------------------------------------------------------
  humidor      Chucho  (service marker-humidor-chucho)
  services     1 in the account now, 2 after
  git HEAD     3f2a91c0d4e1
  page link    https://github.com/MatrixManAtYrService/marker-humidors
  definitions
      markerHumidor.deploy : Text -> Text -> Text -> Text ->{Exception, Cloud} ServiceHash HttpRequest HttpResponse
      ...
------------------------------------------------------------------------
full source (nothing deployed yet):
...
========================================================================

Approve create? Type 'yes' within 300s:
```

Anything other than `yes`, or silence, cancels the request. Approval only happens in that terminal, never over the network. So you can let an AI agent, or a script, use the `humidor` commands, and nothing changes unless you say so.

## Add a humidor and print its cards

Give the humidor a name. Any short name works; it identifies the box, not where it sits.

```bash
humidor create Chucho
```

Approve it in the server terminal. Once it is deployed, the output includes the page URL and where its printable sheet was written:

```json
{
  "status": "created",
  "label": "Chucho",
  "url": "https://YOUR-ACCOUNT.unison-services.cloud/s/marker-humidor-chucho/",
  "sheet": {"print": "qr/marker-humidor-chucho.pdf", "image": "qr/marker-humidor-chucho.png"},
  ...
}
```

Open the URL to see the page. Then print **`qr/marker-humidor-chucho.pdf`** at 100% (also called "actual size"; don't use "fit to page"). It's one page that fits Letter or A4, with a sheet 105 mm wide in the top-left corner. The sheet holds two cards, one above the other, with thin dashed cut lines:

- **QR card:** the humidor's name, the QR code, and "scan to leave feedback".
- **Message card:** what a marker humidor is and how to use it.

Cut along the lines, separating the two cards at the line they share, and tape each one to a different side of the humidor.

The `.png` is the same sheet as an image, for screens or for pasting into a document. Don't print it directly: most browsers and image viewers ignore its print size, and it comes out several times too big.

The message comes from `card_message` in `humidor.toml`, where `{name}` becomes the humidor's name. Lines join into paragraphs, and a blank line starts a new paragraph. After changing it, run `humidor qr NAME` to redraw a sheet.

Tape it to the humidor, scan it with your phone, and leave a test comment.

**About names:**
- A name can be up to 40 letters, digits, spaces and `.,'()-`.
- The page shows it exactly as typed. Its URL uses a lowercase form: "Big Blue (2)" is served at `marker-humidor-big-blue-2`.
- Every command accepts either form, so `humidor comments Chucho` and `humidor comments chucho` do the same thing.

**Lost a card?** `humidor qr Chucho` draws the sheet again. A humidor's URL never changes, so old cards keep working.

## Read the feedback

```bash
humidor ls                  # all your humidors, with their URLs
humidor comments Chucho     # Chucho's comments, newest first
```

```json
{
  "comments": [
    {
      "id": "1795304737677-cfa4f84b",
      "text": "Added 3 blue markers. Tossed a black one with a split tip.",
      "createdAt": 1795304737677,
      "editedAt": null,
      "mine": true,
      "owner": "4c1e9a02"
    }
  ],
  "maxChars": 2000
}
```

- `createdAt` and `editedAt` are milliseconds since 1970 (UTC). The page shows them in the reader's local time.
- `owner` is a short fingerprint of the browser tab that posted the comment. Comments sharing a fingerprint came from the same person in one sitting, which helps when cleaning up spam.
- `mine` is always `true` here, because you are reading as admin.

The output is JSON, so it works with [`jq`](https://jqlang.org/), e.g. `humidor comments Chucho | jq -r '.comments[].text'`.

## Clean up comments

Use the comment `id` from `humidor comments`:

```bash
humidor edit Chucho 1795304737677-cfa4f84b "Added 3 blue markers."   # replace the text
humidor rm Chucho 1795304737677-cfa4f84b                             # delete it
```

The approval prompt shows the comment as it is now and as it would become, so you can check you picked the right one.

## Check that everything is working

```bash
humidor verify              # every humidor
humidor verify Chucho       # just one
```

For each humidor, this checks:
- **registry:** Unison Cloud has a deployment assigned to its name.
- **ledger:** that deployment is the one you last deployed.
- **page and API:** both answer, at the humidor's normal URL and at the URL of that exact version.

It exits with status 1 if anything fails, so you can run it from cron.

`humidor ls` also gives each humidor a `state`:

| state | meaning |
|---|---|
| `deployed` | live, and it is what you last deployed |
| `not-deployed` | nothing is live under its name |
| `drift` | something other than your last deploy is live; run `humidor verify` to see what |
| `unknown` | the server could not reach Unison Cloud (see `live_error`) |

`strays` lists `marker-humidor-*` services in your account that this server doesn't know about, for example ones made on another machine. To manage one from here, see [`humidor adopt`](#manage-from-another-machine-or-replace-a-token).

## Update the pages

After you change the app in `unison/src/` or edit `humidor.toml`, roll the change out to every humidor:

```bash
humidor deploy
```

One approval covers all humidors. The prompt shows the source diff since the last deploy. Comments are kept.

## Retire a humidor

```bash
humidor delete Chucho
```

This removes the page and all its comments. Its QR card will stop working.

Before asking for approval, the server saves the comments to `~/.local/share/humidor/backups/marker-humidor-chucho-<time>.json`, and the prompt says where. You can delete a humidor and later create a new one with the same name; it starts with no comments.

## Manage from another machine, or replace a token

Each humidor has its own admin token, and `humidor edit`, `rm` and `comments` need it. The server generates the token when the humidor is created and keeps it in `~/.local/share/humidor/` on that machine. The token isn't in git, and there's no way to read it back out of Unison Cloud. So a second computer, even one logged in to the same Unison Cloud account, starts out unable to moderate your humidors. `humidor ls` there lists them as `strays`.

Your Unison Cloud login outranks the tokens, though: whoever holds it can redeploy a humidor with a new token. `humidor adopt` does exactly that:

```bash
humidor adopt Chucho
```

After you approve it, the server:
- redeploys Chucho with the current code and a fresh admin token, keeping its comments;
- records it on this machine;
- writes its printable sheet.

Use it to:
- **manage a humidor from a new computer;**
- **recover** after losing `~/.local/share/humidor`;
- **replace a token you think has leaked:** adopting on the same machine swaps the token.

Any other machine's copy of the old token stops working. To keep moderating from both, copy `~/.local/share/humidor/` from one machine to the other instead of adopting, and keep the copy private (`chmod -R go-rwx`).

Give the name as the page shows it ("Chucho"), so the heading keeps its capitalization. If this machine already knows the humidor, its URL form ("chucho") works too.

## Working with an AI agent

Every `humidor` command prints JSON and documents itself with `--help`, and nothing changes without your `yes`. That makes it comfortable to hand day-to-day management to an AI coding agent and just say what you want.

Use two terminals:

1. **Server terminal (yours):** run `humidor serve` and keep it visible. Approval prompts appear here.
2. **Agent terminal:** a shell where the `humidor` command works (`nix develop`, or use `./uv_run.sh`). Start your agent there, in the repo's root. For example:

   ```bash
   nix develop
   claude          # Claude Code; any agent that can run shell commands works
   ```

   This repo includes `CLAUDE.md` and a `humidor` skill in `.claude/skills/`. They tell the agent:
   - to use only the `humidor` commands;
   - to say what it is about to change, and why, before asking for approval;
   - to stop when you say no;
   - never to touch the login or the admin tokens.

   If your agent doesn't read `CLAUDE.md` by itself, point it there first.

Then ask in plain language:

> Set up a new humidor called Big Blue and tell me where its printable sheet is.

> Summarize the feedback on all humidors. Is there evidence they make markers last longer?

> Someone posted the same junk three times on Chucho. Remove it.

> Is everything up? Check all the humidors.

> Reword the intro paragraph to ask how many weeks people have been using it. Try it in the local cloud first, then deploy it to every humidor.

The agent runs `humidor` commands to do it. Reading needs no approval. Anything that changes a page or a comment pauses for your `yes` in the server terminal, and the prompt shows exactly what will change. Say no and the agent is told it was denied.

**How strong is this boundary?**
- The `humidor` commands never hand out a secret, and approval can only come from the server's terminal. So an agent that sticks to them can't change anything without you.
- The agent still runs as you, on your machine, so it could read the login and token files directly. `CLAUDE.md` tells it not to, and you can block those paths in your agent's permission settings. Neither is a hard guarantee.
- For a real wall, run `humidor serve` as a different user or on another machine, and set `HUMIDOR_SERVER_URL` in the agent's shell. The agent's side then has no secrets at all, and you can stop the server whenever you're not managing humidors. The pages stay up regardless.

## Command reference

| Command | What it does | Asks first? |
|---|---|---|
| `humidor serve` | Run the server (owner only, in a visible terminal) | n/a |
| `humidor check` | Setup problems, each with a fix | no |
| `humidor create NAME` | Deploy a page for a new humidor and write its printable sheet | yes |
| `humidor qr NAME` | Draw a humidor's printable sheet again | no |
| `humidor ls` | All humidors, their URLs and state | no |
| `humidor verify [NAME...]` | Test that each page is live and correct | no |
| `humidor comments NAME` | Read a humidor's comments | no |
| `humidor edit NAME ID "TEXT"` | Replace a comment | yes |
| `humidor rm NAME ID` | Delete a comment | yes |
| `humidor deploy` | Update every humidor with the current code and settings | yes |
| `humidor delete NAME` | Back up and remove a humidor and its comments | yes |
| `humidor adopt NAME` | Take charge of an existing humidor from this machine, with a new admin token | yes |

Every command has `--help`. Options and environment variables:

- `create` and `qr` take `--qr-dir DIR` to write the sheet somewhere other than `./qr/`.
- `serve` takes `--port` (default 8100) and `--host` (default `127.0.0.1`).
- `HUMIDOR_SERVER_URL` points the other commands at a server that isn't on this machine.
- `HUMIDOR_HOME` (default `~/.local/share/humidor`) is where the server keeps its state.

## Troubleshooting

Exit codes: 0 ok; 1 a check failed, or the server isn't running; 2 you need to do something, or the command was mistyped (the message says which); 3 you said no, or the approval timed out; 4 another error.

| Message | What to do |
|---|---|
| `cannot reach the humidor server` | Start `humidor serve` in another terminal. (Your pages are fine; only management needs the server.) |
| `Action required: ... auth.login` | Log in to Unison Cloud on the server's machine: run `ucm`, then `auth.login`. |
| `Denied: no terminal to ask for approval` | The server was started without a terminal (e.g. with `&`). Restart it in a normal terminal window. |
| `Denied: timed out waiting for approval` | Nobody typed `yes` in the server terminal within 5 minutes. Run the command again. |
| A humidor is listed under `strays`, or `unknown_humidor` for one you know exists | It was made on another machine, or this machine lost its records. Run `humidor adopt NAME`. |
| `service_exists` when creating | Your Unison Cloud account already has a service with that name, maybe from another machine (see `strays` in `humidor ls`). Pick another name, or `humidor adopt` it if it's yours. |
| The printed sheet is huge or spans two pages | Print the `.pdf`, not the `.png`, at 100% / actual size. |
| `humidor ls` shows `drift` | Something other than your last deploy is live. `humidor verify NAME` shows what differs; `humidor deploy` puts your version back. |
| A deploy fails with a type error | The code in `unison/src/` doesn't compile. Nothing was deployed. Run `pytest tests/test_ucm_programs.py` to see the error. |

Unison Cloud's free tier limits how many services you can run, and each humidor is one service. Check the current limits before creating many; `humidor ls` shows how many services your account has (`services_in_account`).

## How it works

```
humidor <command>  --HTTP-->  humidor serve  --ucm-->  Unison Cloud  <--  people scanning QR cards
 (prints JSON)                 holds your login         marker-humidor-chucho
 you, or an agent              and admin tokens,        marker-humidor-big-blue
                               logs every request,      ...
                               asks before changes      (runs on its own)
 '--------- only needed while you're managing ---------'
```

- **The server is only for management.** Each page is a Unison Cloud service, with its own database, that runs on its own. The server is a convenient, permission-checked way to tell Unison Cloud what to run, and to talk to the pages as admin. Stopping it, or losing it, doesn't affect the pages. To manage them from another machine, though, you'd need the server's state from `~/.local/share/humidor/`, which holds the admin tokens.
- **The server** is the only process with your Unison Cloud login and the humidors' admin tokens. The commands talk to it over HTTP, so it can run on another machine (set `HUMIDOR_SERVER_URL`). Nothing that talks to it ever receives a secret.
- **Each humidor is its own Unison Cloud service,** with its own database and admin token. The server generates the token and keeps it in `~/.local/share/humidor/humidors/` (readable only by you). Admin requests, like reading comments as admin or editing them, go through the server, which adds the token.
- **Every deploy starts clean.** The server forks a base codebase, whose library versions are pinned in `unison/base.md`, loads `unison/src/*.u` from disk, and runs a small generated program. What gets deployed is always what is in the repo.
- **Privacy:** for each comment the app stores only the text, its times, and a SHA-256 of the browser tab's random key. It sets no cookies and logs nothing about visitors. Unison Cloud, as the host, may keep its own request logs.
- **Records:**
  - `./humidor_logs/`: one JSON file per request.
  - `~/.local/share/humidor/deployments.jsonl`: every deploy and delete.
  - `~/.local/share/humidor/backups/`: comments saved before a delete.

## Development

The app is two Unison files:
- `unison/src/marker-humidor.u`: routes, storage, and the deploy and teardown functions.
- `unison/src/page.u`: the HTML page.

The `humidor` command is Python, in `humidor/`.

```bash
nix develop
pytest              # unit tests, plus typechecking the app with real ucm
nix flake check     # ruff + pytest (ucm tests skipped in the sandbox)
./steps.sh          # nix formatting and lint
```

To try a change without deploying, run it in Unison's local cloud and open it in a browser. `CLAUDE.md` has the steps, plus rules for AI agents working in this repo.

The page's API, for scripts:

| Route | |
|---|---|
| `GET /` | the page |
| `GET /api/comments`, `GET /api/comments/<id>` | read |
| `POST /api/comments` with `{"text": ...}` | create; needs an `X-Session-Key` header (32+ characters) |
| `PUT` / `DELETE /api/comments/<id>` | allowed for the session that wrote it, or the admin (`Authorization: Bearer <token>`) |

`markerHumidor.Comment` is stored data. Changing its fields breaks reading existing comments, so add a new type and migrate instead.

Unison gotchas found while building this:
- `Route.request.header` is case-sensitive, and browsers send lowercase header names. Match them case-insensitively (see `markerHumidor.header`).
- Once a route has matched the method and a path prefix, routes doesn't fall through to the next alternative. Use one route per method and prefix, and branch on `Parser.rest`.
- The JSON decoder mishandles `\u` surrogate-pair escapes, so send raw UTF-8. In Python that means `ensure_ascii=False`.
- `@unison/json` must be the version `@unison/routes` was built against, or their `Json` types won't match.
- The local cloud (`Cloud.main.local.serve`) exits when its stdin closes. Keep stdin open, e.g. `sleep 600 | ucm transcript.fork ...`.
