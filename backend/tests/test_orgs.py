def test_roles_and_invitations(alice, client_factory):
    r = alice.post(f"/api/orgs/{alice.org_id}/invitations", {"email": "carol@example.com", "role": "viewer"})
    # Free plan has 1 seat -> blocked server-side.
    assert r.status_code == 402

    # Upgrade via dev billing to allow seats is covered in billing tests; here we set plan directly.
    from app.core.db import db_session
    from app.models import Subscription
    from sqlalchemy import select
    import uuid

    with db_session() as s:
        sub = s.scalar(select(Subscription).where(Subscription.org_id == uuid.UUID(alice.org_id)))
        sub.plan_key = "pro"

    r = alice.post(f"/api/orgs/{alice.org_id}/invitations", {"email": "carol@example.com", "role": "viewer"})
    assert r.status_code == 200
    token = r.json()["invite_url"].rsplit("/", 1)[1]
    carol = client_factory().signup("carol@example.com", org_name="Carol Co")
    r = carol.post("/api/auth/invitations/accept", {"token": token})
    assert r.status_code == 200
    # Viewer can read but not modify
    assert carol.get(f"/api/orgs/{alice.org_id}").status_code == 200
    assert carol.patch(f"/api/orgs/{alice.org_id}", {"name": "x"}).status_code == 403
    assert carol.get(f"/api/orgs/{alice.org_id}/audit-logs").status_code == 403


def test_non_member_gets_404(alice, bob):
    assert bob.get(f"/api/orgs/{alice.org_id}").status_code == 404
    assert bob.get(f"/api/orgs/{alice.org_id}/overview").status_code == 404
    assert bob.patch(f"/api/orgs/{alice.org_id}", {"name": "pwned"}).status_code == 404
    assert bob.delete(f"/api/orgs/{alice.org_id}").status_code == 404


def test_last_owner_protected(alice):
    members = alice.get(f"/api/orgs/{alice.org_id}/members").json()["members"]
    mid = members[0]["id"]
    assert alice.patch(f"/api/orgs/{alice.org_id}/members/{mid}", {"role": "admin"}).status_code == 400
    assert alice.delete(f"/api/orgs/{alice.org_id}/members/{mid}").status_code == 400
