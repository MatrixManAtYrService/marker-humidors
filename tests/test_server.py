"""The humidor server: create, redeploy, delete, verify, the admin proxy, and setup checks."""

from __future__ import annotations

import json
import stat

from humidor.config import slug
from humidor.server.ucm import UcmError
from tests.conftest import CLOUD, HASH_A, HASH_B, FakeSite

SVC = "marker-humidor-chucho"
PAGE = f"{CLOUD}/s/{SVC}/"
COMMENT = {"id": "1-abc", "text": "Too big for the shelf", "createdAt": 1, "editedAt": None, "mine": True}


def chucho_site(extra: dict | None = None, live_hash: str = HASH_B) -> FakeSite:
    page = '<textarea id="text" ...>'
    listing = '{"comments":[],"maxChars":2000}'
    return FakeSite(
        {
            ("GET", f"/s/{SVC}/"): (200, page),
            ("GET", f"/h/{live_hash}/"): (200, page),
            ("GET", f"/h/{live_hash}/api/comments"): (200, listing),
            ("GET", f"/s/{SVC}/api/comments"): (200, json.dumps({"comments": [COMMENT], "maxChars": 2000})),
            ("GET", f"/s/{SVC}/api/comments/1-abc"): (200, json.dumps(COMMENT)),
            ("PUT", f"/s/{SVC}/api/comments/1-abc"): (200, json.dumps({**COMMENT, "text": "cleaned"})),
            ("DELETE", f"/s/{SVC}/api/comments/1-abc"): (200, json.dumps({"deleted": "1-abc"})),
            **(extra or {}),
        }
    )


def token_file(tmp_path, name="chucho"):
    return tmp_path / "home" / "humidors" / f"{name}.token"


def create(client, label="Chucho"):
    return client.post(f"/humidors/{slug(label)}", json={"label": label})


# --- create ---------------------------------------------------------------------


def test_create_deploys_with_name_link_and_a_hidden_token(make_client, tmp_path):
    client, runner, approver = make_client(site=chucho_site())
    resp = create(client, "  Chucho ")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["label"], body["url"], body["hash"]) == ("Chucho", PAGE, HASH_B)
    assert body["hash_url"] == f"{CLOUD}/h/{HASH_B}/"

    [request] = approver.requests
    assert request.action == "create" and "Chucho" in dict(request.summary)["humidor"]
    assert "full source" in request.details

    token = token_file(tmp_path)
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    deploy = runner.transcripts[-1]
    assert 'markerHumidor.deploy "chucho" "Chucho" "https://github.com/example/marker-humidor" token' in deploy
    assert str(token) in deploy and token.read_text() not in deploy

    assert client.get("/health").json()["humidors"] == {"chucho": "Chucho"}
    [row] = client.get("/humidors").json()["humidors"]
    assert (row["name"], row["url"], row["state"]) == ("Chucho", PAGE, "deployed")


def test_denied_create_leaves_nothing_behind(make_client, tmp_path):
    client, runner, _ = make_client(approve=False)
    assert create(client).status_code == 403
    assert not token_file(tmp_path).exists()
    assert client.get("/health").json()["humidors"] == {}
    assert "deploy" not in runner.ran


def test_create_refuses_duplicates_bad_names_and_taken_services(make_client):
    client, runner, _ = make_client(site=chucho_site())
    runner.live = {"marker-humidor-taken": HASH_A}
    assert create(client, "Taken").json()["error"] == "service_exists"
    create(client)
    assert create(client).json()["error"] == "humidor_exists"
    assert client.post("/humidors/other", json={"label": "Chucho"}).json()["error"] == "name_mismatch"
    for bad in ('Chu"cho', "<b>x</b>", "-leading", "x" * 41):
        assert client.post("/humidors/x", json={"label": bad}).status_code == 400, bad


def test_create_needs_a_cloud_login(make_client):
    client, runner, _ = make_client()
    runner.fail = UcmError("please run auth.login", needs_auth=True)
    resp = create(client)
    assert resp.status_code == 499 and "auth.login" in resp.json()["instructions"]


def test_typecheck_failure_never_reaches_approval(make_client):
    client, runner, approver = make_client()
    original = runner.run

    def failing_typecheck(transcript):
        if "run humidor.op" not in transcript:
            raise UcmError("type mismatch")
        return original(transcript)

    runner.run = failing_typecheck  # type: ignore[method-assign]
    assert create(client).status_code == 502
    assert approver.requests == []


# --- redeploy and delete --------------------------------------------------------


def test_redeploy_updates_every_humidor_after_one_approval(make_client):
    client, runner, approver = make_client(site=chucho_site())
    create(client)
    create(client, "Big Blue")
    approver.requests.clear()
    deployed = client.post("/deploy").json()["deployed"]
    assert sorted(d["label"] for d in deployed) == ["Big Blue", "Chucho"]
    assert [r.action for r in approver.requests] == ["deploy"]
    assert "diff since last deploy" in approver.requests[0].details
    assert '"chucho" "Chucho"' in "".join(runner.transcripts[-2:])


def test_redeploy_with_no_humidors_is_refused(make_client):
    client, _, _ = make_client()
    assert client.post("/deploy").json()["error"] == "no_humidors"


def test_delete_backs_up_then_tears_down(make_client, tmp_path):
    client, runner, approver = make_client(site=chucho_site())
    create(client)
    resp = client.delete("/humidors/chucho")
    assert resp.status_code == 200, resp.text
    assert resp.json()["steps"] == ["unassigned", "undeployed", "deleted-name", "teardown"]

    [backup] = (tmp_path / "home" / "backups").glob(f"{SVC}-*.json")
    assert json.loads(backup.read_text())["comments"] == [COMMENT]
    assert str(backup) in dict(approver.requests[-1].summary)["backup"]
    assert 'markerHumidor.teardown "chucho"' in runner.transcripts[-1]

    assert not token_file(tmp_path).exists()
    assert client.get("/health").json()["humidors"] == {}
    assert client.delete("/humidors/chucho").json()["error"] == "unknown_humidor"


def test_denied_delete_keeps_everything(make_client, tmp_path):
    client, _, _ = make_client(site=chucho_site())
    create(client)
    deny, runner, _ = make_client(approve=False, site=chucho_site())
    assert deny.delete("/humidors/chucho").status_code == 403
    assert token_file(tmp_path).exists() and "destroy" not in runner.ran


# --- verify and ls ---------------------------------------------------------------


def test_verify_passes_for_what_we_deployed(make_client):
    client, _, _ = make_client(site=chucho_site())
    create(client)
    body = client.post("/humidors/chucho/verify").json()
    assert body["ok"], body
    assert [r["check"] for r in body["results"]] == [
        "registry",
        "ledger",
        "GET /",
        "GET /h/<hash>/",
        "GET api/comments",
        "GET /h/<hash>/api/comments",
    ]


def test_verify_and_ls_catch_a_foreign_deploy(make_client):
    client, runner, _ = make_client(site=chucho_site(live_hash=HASH_A))
    create(client)
    runner.live[SVC] = HASH_A  # someone deployed something else since
    body = client.post("/humidors/chucho/verify").json()
    assert not body["ok"]
    assert {r["check"]: r["status"] for r in body["results"]}["ledger"] == "fail"
    assert client.get("/humidors").json()["humidors"][0]["state"] == "drift"


def test_verify_is_not_ok_when_the_registry_cannot_be_read(make_client):
    client, runner, _ = make_client(site=chucho_site())
    create(client)
    runner.fail = UcmError("please run auth.login", needs_auth=True)
    body = client.post("/humidors/chucho/verify").json()
    assert not body["ok"]
    statuses = {r["check"]: r["status"] for r in body["results"]}
    assert statuses["registry"] == "skip" and statuses["GET /"] == "pass"


def test_ls_reports_strays_and_service_count(make_client):
    client, runner, _ = make_client(site=chucho_site())
    create(client)
    runner.live.update({"marker-humidor-old": HASH_A, "hello-world": HASH_A})
    body = client.get("/humidors").json()
    assert [s["service"] for s in body["strays"]] == ["marker-humidor-old"]
    assert body["services_in_account"] == 3


def test_ls_without_a_login_still_lists_humidors(make_client):
    client, runner, _ = make_client(site=chucho_site())
    create(client)
    runner.fail = UcmError("please run auth.login", needs_auth=True)
    body = client.get("/humidors").json()
    assert body["humidors"][0]["state"] == "unknown" and "auth.login" in body["live_error"]


# --- admin proxy ------------------------------------------------------------------


def test_admin_get_needs_no_approval_and_carries_the_token(make_client, tmp_path):
    site = chucho_site()
    client, _, approver = make_client(site=site)
    create(client)
    approver.requests.clear()
    resp = client.post("/humidors/chucho/admin", json={"method": "GET", "path": "api/comments"})
    assert resp.json()["body"]["comments"] == [COMMENT]
    assert approver.requests == []
    assert site.requests[-1].headers["authorization"] == f"Bearer {token_file(tmp_path).read_text()}"
    assert token_file(tmp_path).read_text() not in resp.text


def test_admin_edit_shows_current_and_new_then_sends_raw_utf8(make_client):
    site = chucho_site()
    client, _, approver = make_client(site=site)
    create(client)
    approver.requests.clear()
    resp = client.post(
        "/humidors/chucho/admin", json={"method": "PUT", "path": "api/comments/1-abc", "body": {"text": "ok 🖍️"}}
    )
    assert resp.status_code == 200, resp.text
    [request] = approver.requests
    assert request.action == "admin PUT"
    assert "Too big for the shelf" in request.details and "ok 🖍️" in request.details
    assert "🖍️".encode() in site.requests[-1].content  # raw UTF-8, not \\u escapes


def test_denied_admin_delete_is_not_sent(make_client):
    site = chucho_site()
    client, _, _ = make_client(site=site)
    create(client)
    deny, _, _ = make_client(approve=False, site=site)
    resp = deny.post("/humidors/chucho/admin", json={"method": "DELETE", "path": "api/comments/1-abc"})
    assert resp.status_code == 403
    assert all(r.method != "DELETE" for r in site.requests)


def test_admin_rejects_paths_that_escape_the_humidor(make_client):
    client, _, _ = make_client(site=chucho_site())
    create(client)
    for path in ("../hello-world/", "api/../../x", "https://evil.example/", "api/comments?x=1"):
        assert client.post("/humidors/chucho/admin", json={"method": "GET", "path": path}).status_code == 400, path


def test_upstream_errors_are_reported(make_client):
    client, _, _ = make_client(site=chucho_site({("PUT", f"/s/{SVC}/api/comments/1-abc"): (400, "Comment is empty.")}))
    create(client)
    resp = client.post(
        "/humidors/chucho/admin", json={"method": "PUT", "path": "api/comments/1-abc", "body": {"text": " "}}
    )
    assert resp.status_code == 502 and "Comment is empty." in resp.json()["message"]


# --- setup and logs -------------------------------------------------------------------


def test_health_lists_setup_problems_with_fixes(make_client, repo):
    (repo / "humidor.toml").write_text('repo_url = ""\n')
    client, _, _ = make_client()
    setup = {c["check"]: c for c in client.get("/health").json()["setup"]}
    assert not setup["page link set"]["ok"] and "humidor.toml" in setup["page link set"]["fix"]
    assert all("fix" in c for c in setup.values() if not c["ok"])


def test_bad_repo_url_is_rejected(make_client, repo):
    (repo / "humidor.toml").write_text('repo_url = "javascript:alert(1)"\n')
    client, _, _ = make_client()
    assert client.get("/health").json()["error"] == "bad_config"


def test_requests_are_logged(make_client, repo):
    client, _, _ = make_client(site=chucho_site())
    create(client)
    client.post("/humidors/chucho/verify")
    logs = sorted(p.name for p in (repo / "humidor_logs").glob("*.json"))
    assert logs == ["00001-create-chucho.json", "00002-verify-chucho.json"]
