# marker-humidor

Feedback pages for dry-erase marker humidors, deployed to Unison Cloud and managed with the `humidor` CLI. See README.md.

## Rules for agents

- Reach Unison Cloud and the humidors only through `humidor`. Its `--help` is the list of what you may do.
- Never run `ucm auth.login`, read `~/.local/share/unisonlanguage/`, or read `~/.local/share/humidor/` (admin tokens, backups). Never try to approve a request yourself.
- `create`, `adopt`, `deploy`, `delete`, `edit` and `rm` wait for the owner to type `yes` in the server's terminal.
  - Tell the owner what you are asking for and why before running them.
  - Exit code 3 means denied: report it, do not retry.
  - Exit code 2 means the owner must act: relay the instructions.
- `edit` and `rm` change other people's comments. Only do it when the owner asks, naming the comment ID and the reason.
- `delete` destroys that humidor's comments; a backup is kept on the server. Confirm the name with the owner first.
- `adopt` gives a humidor a new admin token, so any other machine managing it loses access. Only run it when the owner asks, or when a humidor shows up under `strays` and the owner confirms it is theirs.
- After `create` or `deploy`, run `humidor verify`. After `create`, tell the owner where the printable sheet (QR card plus message card) was written.
- Do not start `humidor serve` yourself. It belongs to the owner's terminal, and without a terminal every approval is denied.

## Changing the app

- Edit `unison/src/*.u`, then run `pytest tests/test_ucm_programs.py` to typecheck against the pinned libraries in `unison/base.md`. No `lib.install` is needed.
- Never change the fields of `markerHumidor.Comment`; it is stored data.
- Before asking for a deploy, run the change in the local cloud and use it with curl or a browser.
  - Generate a deploy transcript with `humidor.server.ucm.deploy_transcript(...)` and replace `Cloud.main do` with `Cloud.main.local.serve do`.
  - Run it with `sleep 600 | ucm transcript.fork -c ~/.local/share/humidor/base-codebase file.md`; the local cloud exits when its stdin closes.
  - The page is then at http://localhost:8080/s/marker-humidor-NAME/.
- Python: `humidor/` (CLI in `cli.py`, server in `server/`). Run `ruff check`, `ruff format` and `pytest` before finishing.
