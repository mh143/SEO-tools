"""Fix type registry: how each fix is generated, its risk, and the connector operation it maps to."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FixTypeSpec:
    key: str
    label: str
    generator: str  # "ai" | "rule" | "advisory"
    risk: str  # low | medium | high
    operation: str | None  # connector operation, None = export/advisory only
    editable_fields: tuple[str, ...]
    verification: tuple[str, ...]
    requires_approval: bool = True


FIX_TYPES: dict[str, FixTypeSpec] = {
    "meta_title": FixTypeSpec(
        "meta_title", "Page title", "ai", "medium", "set_title", ("title",),
        ("Fetch the live page.", "Confirm the <title> element contains the new title text.")),
    "meta_description": FixTypeSpec(
        "meta_description", "Meta description", "ai", "low", "set_meta_description", ("description",),
        ("Fetch the live page.", "Confirm <meta name=\"description\"> equals the new text.")),
    "h1": FixTypeSpec(
        "h1", "Main heading (H1)", "ai", "medium", "set_title", ("h1",),
        ("Fetch the live page.", "Confirm an <h1> element contains the new heading.")),
    "image_alt": FixTypeSpec(
        "image_alt", "Image alt text", "ai", "low", "set_image_alt", ("alt",),
        ("Fetch the live page.", "Confirm the <img> with the same src has the new alt attribute.")),
    "answer_paragraph": FixTypeSpec(
        "answer_paragraph", "Direct answer below a question heading", "ai", "medium",
        "content_insert_after_heading", ("answer_html",),
        ("Fetch the live page.", "Confirm the answer text appears after the question heading.")),
    "faq_section": FixTypeSpec(
        "faq_section", "FAQ section from existing page content", "ai", "medium", "content_append", ("items",),
        ("Fetch the live page.", "Confirm each FAQ question appears on the page.")),
    "json_ld": FixTypeSpec(
        "json_ld", "Structured data (JSON-LD)", "ai", "medium", "add_json_ld", ("json_ld",),
        ("Fetch the live page.", "Confirm a valid JSON-LD block with the expected @type is present.",
         "Optionally validate with a rich results testing tool.")),
    "content_recommendations": FixTypeSpec(
        "content_recommendations", "Content improvement plan", "ai", "low", None, (),
        ("Re-run the audit after editing the content.",), requires_approval=False),
    "canonical": FixTypeSpec(
        "canonical", "Canonical tag", "rule", "high", "set_canonical", ("canonical_url",),
        ("Fetch the live page.", "Confirm exactly one <link rel=\"canonical\"> pointing to the new URL.")),
    "redirect": FixTypeSpec(
        "redirect", "Redirect rule", "rule", "high", "create_redirect", ("from_url", "to_url", "status"),
        ("Request the old URL without following redirects.", "Confirm a single 301 to the target URL.")),
    "robots_directive": FixTypeSpec(
        "robots_directive", "Robots directive", "rule", "high", "set_robots", ("directive",),
        ("Fetch the live page.", "Confirm the meta robots / X-Robots-Tag matches the intended directive.")),
    "internal_link_update": FixTypeSpec(
        "internal_link_update", "Update internal link target", "rule", "low", "content_replace_href",
        ("new_href",),
        ("Fetch the source page.", "Confirm no link points to the old URL and a link points to the new URL.")),
    "internal_link_add": FixTypeSpec(
        "internal_link_add", "Add contextual internal link", "rule", "low", "content_link_phrase",
        ("phrase", "target_url"),
        ("Fetch the source page.", "Confirm a link to the target URL exists.")),
    "broken_link": FixTypeSpec(
        "broken_link", "Restore or redirect a broken URL", "rule", "high", "create_redirect",
        ("from_url", "to_url", "status"),
        ("Request the broken URL.", "Confirm it returns 200 or a single 301 to a live page.")),
}


def spec_for(fix_type: str | None) -> FixTypeSpec | None:
    return FIX_TYPES.get(fix_type or "")
