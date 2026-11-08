from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, OrgAccess, OrgContext, require_auth, scoped_get
from app.api.serializers import integration_out
from app.core import audit
from app.core.config import get_settings
from app.core.crypto import encrypt_json
from app.core.db import get_db
from app.core.security import hash_token, new_token
from app.crawler.urls import same_site
from app.integrations import search_console
from app.integrations.base import ConnectorError
from app.integrations.registry import available, get_connector
from app.models import ROLE_RANK, Integration, IntegrationStatus, Membership, Role, Website

router = APIRouter(tags=["integrations"])


@router.get("/integrations/providers")
def providers():
    return available()


@router.get("/orgs/{org_id}/integrations")
def list_integrations(o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    rows = db.scalars(select(Integration).where(Integration.org_id == o.org_id).order_by(Integration.created_at.desc())).all()
    return [integration_out(i) for i in rows]


class WPStartIn(BaseModel):
    website_id: uuid.UUID


class WPManualIn(BaseModel):
    website_id: uuid.UUID
    username: str = Field(min_length=1, max_length=200)
    application_password: str = Field(min_length=8, max_length=200)


async def _connect(connector, creds: dict, website: Website) -> tuple[dict, object]:
    identity = await connector.verify_identity(creds)
    if not same_site(identity.site_url or creds["site_url"], website.hostname):
        raise ConnectorError(f"The connected {connector.display_name.split(' (')[0]} site ({identity.site_url}) does "
                             f"not match this website ({website.hostname}).")
    caps = await connector.discover_capabilities(creds, identity)
    return {k: v.to_dict() for k, v in caps.items()}, identity


def _store_connected(db: Session, integ: Integration, creds: dict, caps: dict, identity) -> None:
    integ.encrypted_credentials = encrypt_json(creds)
    integ.capabilities = caps
    integ.status = IntegrationStatus.connected
    integ.external_site_url = identity.site_url
    integ.external_account = identity.account
    integ.display_name = identity.name or identity.site_url
    integ.last_verified_at = datetime.now(UTC)
    integ.error_message = None
    integ.auth_state_hash = None
    integ.auth_state_expires_at = None
    # Only one active integration per website/provider.
    for other in db.scalars(select(Integration).where(
            Integration.website_id == integ.website_id, Integration.provider == integ.provider,
            Integration.id != integ.id, Integration.status == IntegrationStatus.connected)):
        other.status = IntegrationStatus.disconnected
        other.encrypted_credentials = None


@router.post("/orgs/{org_id}/integrations/wordpress/start")
def wordpress_start(body: WPStartIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
                    db: Session = Depends(get_db)):
    website = scoped_get(db, Website, body.website_id, o.org_id)
    connector = get_connector("wordpress")
    try:
        info = asyncio.run(connector.discover(website.root_url))
    except ConnectorError as exc:
        raise HTTPException(status_code=422, detail=exc.user_message) from None
    if not info.get("authorization_endpoint"):
        raise HTTPException(status_code=422, detail=(
            "This WordPress site does not offer Application Password authorization (WordPress 5.6+ over HTTPS is "
            "required, and a security plugin may have disabled it). You can still connect with a manually "
            "created application password."))
    state = new_token(24)
    integ = Integration(org_id=o.org_id, website_id=website.id, provider="wordpress", status=IntegrationStatus.pending,
                        display_name=info.get("name") or website.hostname, external_site_url=info.get("home"),
                        auth_state_hash=hash_token(state), auth_state_expires_at=datetime.now(UTC) + timedelta(minutes=20),
                        capabilities={"_api_root": info["api_root"]}, created_by=o.user.id)
    db.add(integ)
    db.flush()
    s = get_settings()
    cb = f"{s.public_app_url}{s.api_base_path}/integrations/wordpress/callback"
    try:
        url = connector.authorization_url(
            info["authorization_endpoint"], app_name=s.app_name, app_id=s.wordpress_app_id,
            success_url=f"{cb}?{urlencode({'state': state})}", reject_url=f"{cb}?{urlencode({'state': state, 'rejected': '1'})}")
    except ConnectorError as exc:
        raise HTTPException(status_code=422, detail=exc.user_message) from None
    audit.record(db, "integration.authorization_started", org_id=o.org_id, actor_id=o.user.id, target_type="integration",
                 target_id=integ.id, request=request)
    db.commit()
    return {"authorization_url": url, "integration_id": str(integ.id)}


@router.get("/integrations/wordpress/callback")
def wordpress_callback(request: Request, state: str = "", site_url: str = "", user_login: str = "", password: str = "",
                       rejected: str = "", ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    s = get_settings()
    integ = db.scalar(select(Integration).where(Integration.auth_state_hash == hash_token(state or "-")))
    if not integ or integ.status != IntegrationStatus.pending or (integ.auth_state_expires_at or datetime.now(UTC)) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="This authorization link is invalid or has expired.")
    m = db.scalar(select(Membership).where(Membership.org_id == integ.org_id, Membership.user_id == ctx.user.id))
    if not m or ROLE_RANK[m.role] < ROLE_RANK[Role.admin]:
        raise HTTPException(status_code=403, detail="Only organization admins can complete this connection.")
    dest = f"{s.public_app_url}/app/{integ.org_id}/integrations"
    if rejected or not (user_login and password):
        integ.status = IntegrationStatus.error
        integ.error_message = "Authorization was declined on the WordPress site."
        integ.auth_state_hash = None
        db.commit()
        return RedirectResponse(f"{dest}?{urlencode({'result': 'rejected'})}", status_code=303)
    website = db.get(Website, integ.website_id)
    creds = {"site_url": site_url, "user_login": user_login, "password": password,
             "api_root": (integ.capabilities or {}).get("_api_root")}
    connector = get_connector("wordpress")
    try:
        caps, identity = asyncio.run(_connect(connector, creds, website))
    except ConnectorError as exc:
        integ.status = IntegrationStatus.error
        integ.error_message = exc.user_message
        integ.auth_state_hash = None
        db.commit()
        return RedirectResponse(f"{dest}?{urlencode({'result': 'error'})}", status_code=303)
    _store_connected(db, integ, creds, caps, identity)
    audit.record(db, "integration.connected", org_id=integ.org_id, actor_id=ctx.user.id, target_type="integration",
                 target_id=integ.id, request=request, data={"provider": "wordpress", "site": identity.site_url})
    db.commit()
    return RedirectResponse(f"{dest}?{urlencode({'result': 'connected'})}", status_code=303)


@router.post("/orgs/{org_id}/integrations/wordpress/manual")
def wordpress_manual(body: WPManualIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
                     db: Session = Depends(get_db)):
    """Connect with an application password the user created in WordPress (Users → Profile)."""
    website = scoped_get(db, Website, body.website_id, o.org_id)
    connector = get_connector("wordpress")
    try:
        info = asyncio.run(connector.discover(website.root_url))
        creds = {"site_url": info.get("home") or website.root_url, "user_login": body.username.strip(),
                 "password": body.application_password.strip(), "api_root": info["api_root"]}
        caps, identity = asyncio.run(_connect(connector, creds, website))
    except ConnectorError as exc:
        raise HTTPException(status_code=422, detail=exc.user_message) from None
    integ = Integration(org_id=o.org_id, website_id=website.id, provider="wordpress", status=IntegrationStatus.pending,
                        created_by=o.user.id)
    db.add(integ)
    db.flush()
    _store_connected(db, integ, creds, caps, identity)
    audit.record(db, "integration.connected", org_id=o.org_id, actor_id=o.user.id, target_type="integration",
                 target_id=integ.id, request=request, data={"provider": "wordpress", "method": "manual"})
    db.commit()
    return integration_out(integ)


@router.post("/orgs/{org_id}/integrations/{integration_id}/refresh")
def refresh_integration(integration_id: uuid.UUID, o: OrgContext = Depends(OrgAccess(Role.admin)),
                        db: Session = Depends(get_db)):
    from app.core.crypto import decrypt_json

    integ = scoped_get(db, Integration, integration_id, o.org_id)
    if integ.status != IntegrationStatus.connected or not integ.encrypted_credentials:
        raise HTTPException(status_code=409, detail="Integration is not connected.")
    website = db.get(Website, integ.website_id)
    if integ.provider == search_console.PROVIDER:
        try:
            creds = decrypt_json(integ.encrypted_credentials)
            sites = asyncio.run(search_console.list_sites(creds))
            props = search_console.matching_properties(sites, website.hostname)
            integ.capabilities = {**(integ.capabilities or {}), "properties": props}
            integ.last_verified_at, integ.error_message = datetime.now(UTC), None
            if creds.get("property") not in props:
                integ.error_message = "The selected Search Console property is no longer accessible."
        except ConnectorError as exc:
            integ.status, integ.error_message = IntegrationStatus.error, exc.user_message
        db.commit()
        return integration_out(integ)
    try:
        caps, identity = asyncio.run(_connect(get_connector(integ.provider), decrypt_json(integ.encrypted_credentials), website))
        integ.capabilities, integ.last_verified_at, integ.error_message = caps, datetime.now(UTC), None
    except ConnectorError as exc:
        integ.status, integ.error_message = IntegrationStatus.error, exc.user_message
    db.commit()
    return integration_out(integ)


@router.delete("/orgs/{org_id}/integrations/{integration_id}")
def disconnect(integration_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
               db: Session = Depends(get_db)):
    integ = scoped_get(db, Integration, integration_id, o.org_id)
    integ.status = IntegrationStatus.disconnected
    integ.encrypted_credentials = None  # credentials are destroyed immediately
    audit.record(db, "integration.disconnected", org_id=o.org_id, actor_id=o.user.id, target_type="integration",
                 target_id=integ.id, request=request)
    db.commit()
    notes = {
        "wordpress": "You can also revoke the application password in WordPress under Users → Profile → "
                     "Application Passwords.",
        "shopify": "You can also uninstall or rotate the custom app in Shopify admin → Settings → Apps and sales channels.",
        "wix": "You can also delete the API key in the Wix API Keys Manager.",
        search_console.PROVIDER: "You can also remove access at myaccount.google.com → Security → Third-party access.",
    }
    return {**integration_out(integ), "note": "Credentials deleted. " + notes.get(integ.provider, "")}


# ---------------------------------------------------------------------------- Shopify
class ShopifyIn(BaseModel):
    website_id: uuid.UUID
    shop: str = Field(min_length=1, max_length=255)
    access_token: str = Field(min_length=8, max_length=255)


@router.post("/orgs/{org_id}/integrations/shopify")
def shopify_connect(body: ShopifyIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
                    db: Session = Depends(get_db)):
    """Connect a Shopify store with a custom app's Admin API access token."""
    website = scoped_get(db, Website, body.website_id, o.org_id)
    connector = get_connector("shopify")
    try:
        creds = {"shop": connector.normalize_shop(body.shop), "access_token": body.access_token.strip()}
        caps, identity = asyncio.run(_connect(connector, creds, website))
    except ConnectorError as exc:
        raise HTTPException(status_code=422, detail=exc.user_message) from None
    integ = Integration(org_id=o.org_id, website_id=website.id, provider="shopify", status=IntegrationStatus.pending,
                        created_by=o.user.id)
    db.add(integ)
    db.flush()
    _store_connected(db, integ, creds, caps, identity)
    audit.record(db, "integration.connected", org_id=o.org_id, actor_id=o.user.id, target_type="integration",
                 target_id=integ.id, request=request, data={"provider": "shopify", "shop": creds["shop"]})
    db.commit()
    return integration_out(integ)


# ---------------------------------------------------------------------------- Wix
class WixIn(BaseModel):
    website_id: uuid.UUID
    site_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    api_key: str = Field(min_length=16, max_length=4096)


@router.post("/orgs/{org_id}/integrations/wix")
def wix_connect(body: WixIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
                db: Session = Depends(get_db)):
    """Connect a Wix site with an API key (API Keys Manager) and its site ID."""
    website = scoped_get(db, Website, body.website_id, o.org_id)
    connector = get_connector("wix")
    creds = {"site_id": body.site_id.strip(), "api_key": body.api_key.strip()}
    try:
        caps, identity = asyncio.run(_connect(connector, creds, website))
    except ConnectorError as exc:
        raise HTTPException(status_code=422, detail=exc.user_message) from None
    integ = Integration(org_id=o.org_id, website_id=website.id, provider="wix", status=IntegrationStatus.pending,
                        created_by=o.user.id)
    db.add(integ)
    db.flush()
    _store_connected(db, integ, creds, caps, identity)
    audit.record(db, "integration.connected", org_id=o.org_id, actor_id=o.user.id, target_type="integration",
                 target_id=integ.id, request=request, data={"provider": "wix"})
    db.commit()
    return integration_out(integ)


# ---------------------------------------------------------------------------- Google Search Console
class GoogleStartIn(BaseModel):
    website_id: uuid.UUID


@router.post("/orgs/{org_id}/integrations/google/start")
def google_start(body: GoogleStartIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
                 db: Session = Depends(get_db)):
    if not search_console.configured():
        raise HTTPException(status_code=422, detail=(
            "Google Search Console is not configured on this server. An administrator must set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET (OAuth web client) first."))
    website = scoped_get(db, Website, body.website_id, o.org_id)
    state = new_token(24)
    integ = Integration(org_id=o.org_id, website_id=website.id, provider=search_console.PROVIDER,
                        status=IntegrationStatus.pending, display_name="Google Search Console",
                        auth_state_hash=hash_token(state), auth_state_expires_at=datetime.now(UTC) + timedelta(minutes=20),
                        capabilities={}, created_by=o.user.id)
    db.add(integ)
    db.flush()
    audit.record(db, "integration.authorization_started", org_id=o.org_id, actor_id=o.user.id,
                 target_type="integration", target_id=integ.id, request=request, data={"provider": search_console.PROVIDER})
    db.commit()
    return {"authorization_url": search_console.authorization_url(state), "integration_id": str(integ.id)}


@router.get("/integrations/google/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = "",
                    ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    s = get_settings()
    integ = db.scalar(select(Integration).where(Integration.auth_state_hash == hash_token(state or "-"),
                                                Integration.provider == search_console.PROVIDER))
    if not integ or integ.status != IntegrationStatus.pending or (integ.auth_state_expires_at or datetime.now(UTC)) < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="This authorization link is invalid or has expired.")
    m = db.scalar(select(Membership).where(Membership.org_id == integ.org_id, Membership.user_id == ctx.user.id))
    if not m or ROLE_RANK[m.role] < ROLE_RANK[Role.admin]:
        raise HTTPException(status_code=403, detail="Only organization admins can complete this connection.")
    dest = f"{s.public_app_url}/app/{integ.org_id}/integrations"
    integ.auth_state_hash = None
    if error or not code:
        integ.status, integ.error_message = IntegrationStatus.error, "Access was declined on the Google consent screen."
        db.commit()
        return RedirectResponse(f"{dest}?{urlencode({'result': 'rejected'})}", status_code=303)
    website = db.get(Website, integ.website_id)
    try:
        tokens = asyncio.run(search_console.exchange_code(code))
        creds = {"refresh_token": tokens["refresh_token"]}
        props = search_console.matching_properties(asyncio.run(search_console.list_sites(creds)), website.hostname)
        if not props:
            raise ConnectorError(f"This Google account has no verified Search Console property for {website.hostname}. "
                                 "Add and verify the site in Search Console, then connect again.")
    except ConnectorError as exc:
        integ.status, integ.error_message = IntegrationStatus.error, exc.user_message
        db.commit()
        return RedirectResponse(f"{dest}?{urlencode({'result': 'error'})}", status_code=303)
    creds["property"] = props[0]
    integ.encrypted_credentials = encrypt_json(creds)
    integ.capabilities = {"properties": props, "kind": "data"}
    integ.status = IntegrationStatus.connected
    integ.external_site_url = props[0]
    integ.external_account = "Google account"
    integ.display_name = f"Search Console · {props[0]}"
    integ.last_verified_at, integ.error_message = datetime.now(UTC), None
    for other in db.scalars(select(Integration).where(
            Integration.website_id == integ.website_id, Integration.provider == integ.provider,
            Integration.id != integ.id, Integration.status == IntegrationStatus.connected)):
        other.status, other.encrypted_credentials = IntegrationStatus.disconnected, None
    audit.record(db, "integration.connected", org_id=integ.org_id, actor_id=ctx.user.id, target_type="integration",
                 target_id=integ.id, request=request, data={"provider": search_console.PROVIDER, "property": props[0]})
    db.commit()
    return RedirectResponse(f"{dest}?{urlencode({'result': 'connected'})}", status_code=303)


class PropertyIn(BaseModel):
    property: str = Field(min_length=3, max_length=2048)


@router.post("/orgs/{org_id}/integrations/{integration_id}/property")
def google_set_property(integration_id: uuid.UUID, body: PropertyIn, o: OrgContext = Depends(OrgAccess(Role.admin)),
                        db: Session = Depends(get_db)):
    from app.core.crypto import decrypt_json

    integ = scoped_get(db, Integration, integration_id, o.org_id)
    if integ.provider != search_console.PROVIDER or integ.status != IntegrationStatus.connected:
        raise HTTPException(status_code=409, detail="Not a connected Search Console integration.")
    if body.property not in (integ.capabilities or {}).get("properties", []):
        raise HTTPException(status_code=422, detail="That property does not match this website.")
    creds = decrypt_json(integ.encrypted_credentials)
    creds["property"] = body.property
    integ.encrypted_credentials = encrypt_json(creds)
    integ.external_site_url = body.property
    integ.display_name = f"Search Console · {body.property}"
    db.commit()
    return integration_out(integ)


@router.get("/orgs/{org_id}/websites/{website_id}/search-console")
def search_console_performance(website_id: uuid.UUID, days: int = 28, o: OrgContext = Depends(OrgAccess()),
                               db: Session = Depends(get_db)):
    from app.core.crypto import decrypt_json

    website = scoped_get(db, Website, website_id, o.org_id)
    integ = db.scalar(select(Integration).where(
        Integration.org_id == o.org_id, Integration.website_id == website.id,
        Integration.provider == search_console.PROVIDER, Integration.status == IntegrationStatus.connected))
    if integ is None:
        return {"connected": False, "configured": search_console.configured()}
    try:
        data = asyncio.run(search_console.performance(decrypt_json(integ.encrypted_credentials), days))
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=exc.user_message) from None
    return {"connected": True, "integration_id": str(integ.id), **data}
