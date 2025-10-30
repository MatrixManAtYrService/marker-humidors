---
name: humidor
description: Check, create, redeploy, delete and verify marker humidor feedback pages, and read or moderate their comments, through the humidor CLI. Use when asked what humidors exist, to add or remove one, to ship a code change, to print a humidor's cards, or to look at feedback.
---

# humidor

1. Run `humidor check`.
   - If it cannot reach the server, ask the owner to start `humidor serve` in a terminal. Do not start it yourself.
   - Relay any setup problem's `fix`.
2. `humidor ls` gives each humidor's `state`:
   - `deployed`: fine.
   - `drift`: run `humidor verify` and report what differs.
   - `unknown`: the server is not logged in to Unison Cloud; relay `live_error`.
3. `humidor verify [NAME...]` exits 1 on any failed or skipped check. Quote the failing `results`.
4. `humidor comments NAME` is read-only. Use it to summarise feedback.
5. Commands that need the owner's approval in the server terminal:
   - `create NAME`: tell the owner where the printable sheet was written, so they can print it and cut out the two cards.
   - `deploy`: after a code change; then run `humidor verify`.
   - `edit` / `rm`: only when asked, naming the comment ID and the reason.
   - `adopt NAME`: for a humidor listed under `strays` (made on another machine) or a token that may have leaked. Confirm with the owner first; other machines lose access.
   - `delete NAME`: confirm the name first; it destroys that humidor's comments, though a backup is kept on the server.

   Say what will change and why before running any of them. Exit 3 means denied: stop.
