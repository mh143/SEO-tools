def test_signup_login_logout(client_factory):
    c = client_factory().signup("a@example.com")
    me = c.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["organizations"][0]["role"] == "owner"
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401

    c2 = client_factory()
    r = c2.post("/api/auth/login", {"email": "a@example.com", "password": "wrong-password!"})
    assert r.status_code == 401
    r = c2.post("/api/auth/login", {"email": "A@example.com", "password": "correct-horse-battery"})
    assert r.status_code == 200


def test_weak_password_rejected(client_factory):
    r = client_factory().post("/api/auth/signup", {"email": "x@example.com", "password": "short"})
    assert r.status_code == 422


def test_duplicate_email(client_factory):
    client_factory().signup("dup@example.com")
    r = client_factory().post("/api/auth/signup", {"email": "dup@example.com", "password": "another-long-pass"})
    assert r.status_code == 409


def test_csrf_required_for_unsafe_methods(alice):
    # Same session cookie, no CSRF header -> rejected.
    r = alice.c.post(f"/api/orgs/{alice.org_id}/notifications/read")
    assert r.status_code == 403
    r = alice.c.post(f"/api/orgs/{alice.org_id}/notifications/read", headers={"X-CSRF-Token": "nope"})
    assert r.status_code == 403
    assert alice.post(f"/api/orgs/{alice.org_id}/notifications/read").status_code == 200


def test_session_cookie_flags(client_factory):
    c = client_factory()
    r = c.post("/api/auth/signup", {"email": "f@example.com", "password": "correct-horse-battery"})
    cookies = r.headers.get_list("set-cookie")
    session_cookie = next(x for x in cookies if x.startswith("rl_session="))
    assert "HttpOnly" in session_cookie
    assert "samesite=lax" in session_cookie.lower()


def test_password_change_revokes_other_sessions(client_factory):
    a1 = client_factory().signup("pw@example.com")
    a2 = client_factory()
    r = a2.post("/api/auth/login", {"email": "pw@example.com", "password": "correct-horse-battery"})
    a2.csrf = r.json()["csrf_token"]
    r = a1.post("/api/auth/password", {"current_password": "correct-horse-battery", "new_password": "new-long-password-1"})
    assert r.status_code == 200
    assert a2.get("/api/auth/me").status_code == 401
    assert a1.get("/api/auth/me").status_code == 200


def test_delete_account_removes_sole_owner_org(client_factory, db):
    from app.models import Organization

    c = client_factory().signup("del@example.com")
    org_id = c.org_id
    r = c.post("/api/auth/delete-account", {"password": "correct-horse-battery"})
    assert r.status_code == 200
    import uuid

    assert db.get(Organization, uuid.UUID(org_id)) is None
