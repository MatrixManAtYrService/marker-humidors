"""humidor adopt: take charge of an existing humidor from this machine."""

from __future__ import annotations

from fastapi.testclient import TestClient

from humidor.server.main import Settings, create_app
from tests.conftest import HASH_A, HASH_B, FakeApprover, FakeSite
from tests.test_server import SVC, chucho_site, create, token_file


def second_machine(repo, tmp_path, runner, approve=True):
    """A server with its own, empty home: another computer logged in to the same account."""
    approver = FakeApprover(approve)
    app = create_app(
        Settings(root=repo, home=tmp_path / "other-home"), runner=runner, approver=approver, http=chucho_site().client()
    )
    return TestClient(app), approver


def test_adopt_a_humidor_made_on_another_machine(make_client, repo, tmp_path):
    first, runner, _ = make_client(site=chucho_site())
    create(first)
    old_token = token_file(tmp_path).read_text()

    other, approver = second_machine(repo, tmp_path, runner)
    assert other.get("/humidors").json()["strays"][0]["service"] == SVC
    runner.next_hash = HASH_A
    resp = other.post("/humidors/chucho/adopt", json={"label": "Chucho"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["label"], body["replaced_local_token"]) == ("adopted", "Chucho", False)
    assert body["previous_hash"] == HASH_B and body["hash"] == HASH_A

    [request] = approver.requests
    assert request.action == "adopt" and "does not manage it yet" in dict(request.summary)["this machine"]
    new_token = (tmp_path / "other-home" / "humidors" / "chucho.token").read_text()
    assert new_token != old_token and new_token not in runner.transcripts[-1]
    assert other.get("/humidors").json()["humidors"][0]["state"] == "deployed"


def test_adopt_on_the_same_machine_rotates_the_token(make_client, tmp_path):
    client, runner, approver = make_client(site=chucho_site())
    create(client)
    old_token = token_file(tmp_path).read_text()
    resp = client.post("/humidors/chucho/adopt", json={"label": "chucho"})  # URL form
    assert resp.status_code == 200, resp.text
    assert resp.json()["replaced_local_token"] is True
    assert resp.json()["label"] == "Chucho"  # kept the known display name
    assert token_file(tmp_path).read_text() != old_token
    assert "will be replaced" in dict(approver.requests[-1].summary)["this machine"]


def test_denied_adopt_keeps_the_old_token(make_client, tmp_path):
    client, runner, _ = make_client(site=chucho_site())
    create(client)
    old_token = token_file(tmp_path).read_text()
    old_meta = client.get("/humidors").json()["humidors"]

    deny, deny_runner, _ = make_client(approve=False, site=chucho_site())
    deny_runner.live = dict(runner.live)
    resp = deny.post("/humidors/chucho/adopt", json={"label": "Chucho"})
    assert resp.status_code == 403
    assert token_file(tmp_path).read_text() == old_token
    assert client.get("/humidors").json()["humidors"][0]["name"] == old_meta[0]["name"]


def test_denied_adopt_on_a_new_machine_leaves_nothing(make_client, repo, tmp_path):
    first, runner, _ = make_client(site=chucho_site())
    create(first)
    other, _ = second_machine(repo, tmp_path, runner, approve=False)
    assert other.post("/humidors/chucho/adopt", json={"label": "Chucho"}).status_code == 403
    assert other.get("/health").json()["humidors"] == {}


def test_adopt_needs_an_existing_service(make_client):
    client, _, _ = make_client(site=FakeSite())
    resp = client.post("/humidors/ghost/adopt", json={"label": "Ghost"})
    assert resp.status_code == 404 and "humidor create" in resp.json()["message"]
    assert client.post("/humidors/other/adopt", json={"label": "Chucho"}).json()["error"] == "name_mismatch"
