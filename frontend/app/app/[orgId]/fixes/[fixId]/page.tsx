"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { BeforeAfter } from "@/components/Diff";
import { Badge, Button, Card, ErrorState, Field, fmtDate, JsonBlock, Loading, Notice, PageHeader, StatusBadge, useAction } from "@/components/ui";
import { api, post, patch } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { hasRole, useSession } from "@/lib/session";

const BUSY = ["applying", "verifying", "externally_applied_unverified"];

function textOf(v: any): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  return JSON.stringify(v, null, 2);
}

function compare(fix: any): { label: string; before: string; after: string }[] {
  const a = fix.after || {}, b = fix.before || {};
  switch (fix.fix_type) {
    case "meta_title": return [{ label: "<title>", before: b.title, after: a.title }];
    case "meta_description": return [{ label: "Meta description", before: b.description, after: a.description }];
    case "h1": return [{ label: "H1", before: b.h1, after: a.h1 }];
    case "image_alt": return [{ label: `alt for ${b.src}`, before: b.alt ?? "(missing attribute)", after: a.alt }];
    case "answer_paragraph": return [{ label: `Answer below “${b.question}”`, before: b.answer_preview, after: a.answer_html }];
    case "faq_section": return [{ label: "FAQ section", before: (b.existing_questions || []).join("\n"), after: (a.items || []).map((x: any) => `Q: ${x.question}\nA: ${x.answer}`).join("\n\n") }];
    case "json_ld": return [{ label: "JSON-LD", before: b.invalid_snippet || (b.existing_types || []).join(", "), after: a.json_ld }];
    case "canonical": return [{ label: "Canonical", before: (b.canonical_tags || []).join("\n"), after: a.canonical_url }];
    case "internal_link_update": return [{ label: `Link on ${b.source_url}`, before: b.old_href, after: a.new_href }];
    case "internal_link_add": return [{ label: "New contextual link", before: "", after: `“${a.phrase}” → ${a.target_url}` }];
    case "redirect": case "broken_link": return [{ label: "Redirect", before: b.url, after: `${a.from_url} → ${a.to_url} (${a.status})` }];
    case "robots_directive": return [{ label: "Robots directive", before: (b.directives || []).join(", "), after: a.directive }];
    default: return [{ label: "Proposed change", before: textOf(b), after: textOf(a) }];
  }
}

function Editor({ fix, onSave, busy }: { fix: any; onSave: (after: any) => void; busy: boolean }) {
  const [draft, setDraft] = useState<any>(fix.after || {});
  useEffect(() => setDraft(fix.after || {}), [fix.id, fix.updated_at]);
  const fields: string[] = fix.spec?.editable_fields || [];
  if (!fields.length) return null;
  return (
    <Card title="Edit draft">
      <div className="space-y-3">
        {fields.map((f) => {
          if (f === "items") {
            const items = draft.items || [];
            return (
              <div key={f} className="space-y-2">
                {items.map((it: any, idx: number) => (
                  <div key={idx} className="grid gap-2 rounded border p-2">
                    <input className="input" value={it.question} aria-label={`Question ${idx + 1}`} onChange={(e) => { const n = [...items]; n[idx] = { ...it, question: e.target.value }; setDraft({ ...draft, items: n }); }} />
                    <textarea className="input" rows={2} value={it.answer} aria-label={`Answer ${idx + 1}`} onChange={(e) => { const n = [...items]; n[idx] = { ...it, answer: e.target.value }; setDraft({ ...draft, items: n }); }} />
                    <button className="text-left text-xs text-red-600" onClick={() => setDraft({ ...draft, items: items.filter((_: any, j: number) => j !== idx) })}>Remove</button>
                  </div>
                ))}
                <Button size="sm" variant="secondary" onClick={() => setDraft({ ...draft, items: [...items, { question: "", answer: "" }] })}>Add question</Button>
              </div>
            );
          }
          const long = ["answer_html", "json_ld", "description"].includes(f);
          return (
            <Field key={f} label={f.replace(/_/g, " ")}>
              {long ? <textarea className="input mono" rows={f === "json_ld" ? 10 : 4} value={draft[f] ?? ""} name={f} onChange={(e) => setDraft({ ...draft, [f]: e.target.value })} />
                : <input className="input" value={draft[f] ?? ""} name={f} onChange={(e) => setDraft({ ...draft, [f]: e.target.value })} />}
              {f === "title" && <span className="text-xs text-slate-500">{(draft[f] || "").length} characters</span>}
              {f === "description" && <span className="text-xs text-slate-500">{(draft[f] || "").length} characters</span>}
            </Field>
          );
        })}
        <p className="text-xs text-slate-500">You are responsible for the accuracy of manual edits. Edits are validated (no scripts or markup in text fields) and reset approval.</p>
        <Button variant="secondary" busy={busy} onClick={() => onSave(Object.fromEntries(fields.map((f) => [f, draft[f] ?? (f === "items" ? [] : "")])))} testId="save-draft">Save draft</Button>
      </div>
    </Card>
  );
}

export default function FixEditor({ params }: { params: { fixId: string } }) {
  const { orgId, role } = useSession();
  const path = `/orgs/${orgId}/fixes/${params.fixId}`;
  const { data: fix, error, loading, reload, setData } = useApi<any>(path, { pollMs: 2500, pollWhile: (d) => BUSY.includes(d.status) });
  const act = useAction();
  const [copied, setCopied] = useState(false);
  if (loading) return <Loading />;
  if (error) return <ErrorState error={error} onRetry={reload} />;

  // After an action, re-fetch through the hook so polling resumes while the fix is applying/verifying.
  const doAction = (a: string, body?: any) => act.run(async () => { setData(await post(`${path}/${a}`, body)); await reload(); });
  // Rollback runs in the background without an intermediate status: follow up until it resolves.
  const doRollback = () => act.run(async () => {
    const before = await post<any>(`${path}/rollback`);
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      const now = await api<any>(path);
      setData(now);
      if (now.status !== before.status || (now.error && now.error !== before.error)) return;
    }
  });
  const s = fix.status;
  const isAdmin = hasRole(role, "admin"), isEditor = hasRole(role, "editor");
  const ready = Object.keys(fix.after || {}).length > 0 && !(fix.validation?.errors || []).length;
  const editable = !["applying", "verifying", "verified"].includes(s) && isEditor;

  async function copy() {
    const r = await fetch(`/api${path}/export?format=txt`);
    await navigator.clipboard.writeText(await r.text());
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <>
      <PageHeader title={fix.spec?.label || fix.fix_type} back={{ href: `/app/${orgId}/fixes`, label: "Fix queue" }}
        subtitle={<span className="flex flex-wrap items-center gap-2"><StatusBadge s={s} /><Badge>risk: {fix.risk_level}</Badge><Badge>confidence: {fix.confidence}</Badge>
          <Badge tone={fix.generator.startsWith("ai") ? "bg-violet-100 text-violet-800" : undefined}>{fix.generator === "rule" ? "rule-based" : fix.generator}</Badge>
          <span className="break-all">{fix.url}</span></span>} />
      {fix.generator === "ai:mock" && <div className="mb-4"><Notice kind="warning">Generated by the mock AI provider (development/testing). This is placeholder output, not a real AI suggestion.</Notice></div>}
      {fix.error && <div className="mb-4"><Notice kind={s === "failed" ? "error" : "warning"} testId="fix-error">{fix.error}</Notice></div>}
      {act.error && <div className="mb-4"><Notice kind="error">{act.error}</Notice></div>}
      {BUSY.includes(s) && <div className="mb-4"><Notice kind="info" testId="fix-busy">{s === "applying" ? "Publishing…" : "Checking the live page to verify the change…"} This page updates automatically.</Notice></div>}
      {s === "verified" && <div className="mb-4"><Notice kind="success" testId="fix-verified">Verified: the live page shows this change ({fmtDate(fix.verified_at)}).</Notice></div>}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Before and after">
            {Object.keys(fix.after || {}).length === 0 ? <p className="text-sm text-slate-500">No valid draft. {fix.validation?.errors?.length ? "The generated suggestion was rejected; edit the draft manually or regenerate." : ""}</p>
              : compare(fix).map((c) => <BeforeAfter key={c.label} label={c.label} before={c.before || ""} after={c.after || ""} />)}
            {fix.rationale && <p className="mt-4 text-sm text-slate-600"><b>Rationale:</b> {fix.rationale}</p>}
            {fix.validation?.warnings?.length > 0 && <div className="mt-3"><Notice kind="warning">{fix.validation.warnings.join(" ")}</Notice></div>}
            {fix.validation?.errors?.length > 0 && <div className="mt-3"><Notice kind="error"><b>Validation errors:</b><ul className="list-disc pl-5">{fix.validation.errors.map((e: string) => <li key={e}>{e}</li>)}</ul></Notice></div>}
          </Card>
          {editable && <Editor fix={fix} busy={act.busy} onSave={(after) => act.run(async () => setData(await patch(path, { after })))} />}
          {fix.verification_result?.checks && (
            <Card title="Live verification">
              <p className="mb-2 text-sm text-slate-500">Checked {fmtDate(fix.verification_result.checked_at)} · attempt {fix.verification_attempts} · {fix.verification_result.passed ? "passed" : "not passed"}</p>
              <table className="w-full text-sm"><tbody>{fix.verification_result.checks.map((c: any, i: number) => (
                <tr key={i} className="border-t align-top"><td className="py-1 pr-2">{c.passed ? "✅" : "❌"}</td><td className="pr-2">{c.name}</td><td className="break-all text-xs text-slate-500">expected: {textOf(c.expected)}<br />observed: {textOf(c.observed)}</td></tr>))}</tbody></table>
              {fix.verification_result.error && <p className="mt-2 text-sm text-red-700">{fix.verification_result.error}</p>}
            </Card>
          )}
          {(fix.provider_response && Object.keys(fix.provider_response).length > 0) && (
            <Card title="Provider record"><JsonBlock value={{ resource: fix.provider_resource, response: fix.provider_response, original_state_fields: Object.keys(fix.original_state || {}) }} /></Card>
          )}
        </div>
        <div className="space-y-4">
          <Card title="Actions">
            <div className="flex flex-col gap-2">
              {isEditor && ["drafted", "rejected", "failed"].includes(s) && ready && <Button testId="submit-fix" busy={act.busy} onClick={() => doAction("submit")}>Submit for approval</Button>}
              {isAdmin && s === "awaiting_approval" && <>
                <Button testId="approve-fix" busy={act.busy} onClick={() => doAction("approve")}>Approve</Button>
                <Button variant="secondary" busy={act.busy} onClick={() => doAction("reject", { reason: prompt("Reason for rejecting (optional)") || "" })}>Reject</Button>
              </>}
              {isAdmin && s === "approved" && (fix.direct_apply_supported
                ? <Button testId="publish-fix" busy={act.busy} onClick={() => doAction("apply")}>Publish to site</Button>
                : <Notice kind="info">Direct publishing unavailable: {fix.apply_unsupported_reason}</Notice>)}
              {isEditor && ["drafted", "awaiting_approval", "approved"].includes(s) && ready && fix.fix_type !== "content_recommendations" &&
                <Button variant="secondary" busy={act.busy} onClick={() => doAction("mark-applied")} testId="mark-applied">I applied it myself — verify</Button>}
              {isEditor && (["verifying", "verified"].includes(s) || (s === "failed" && (fix.applied_at || fix.verification_attempts))) &&
                <Button variant="secondary" busy={act.busy} onClick={() => doAction("verify")}>Re-verify live page</Button>}
              {isAdmin && fix.rollback_ref && Object.keys(fix.rollback_ref).length > 0 && ["verified", "failed", "verifying"].includes(s) &&
                <Button variant="danger" busy={act.busy} onClick={() => confirm("Restore the original content on the live site?") && doRollback()} testId="rollback-fix">Roll back</Button>}
              <div className="mt-2 flex flex-wrap gap-2 border-t pt-3 text-sm">
                <Button size="sm" variant="secondary" onClick={copy}>{copied ? "Copied" : "Copy instructions"}</Button>
                <a className="rounded-md border border-slate-300 px-2.5 py-1 text-xs no-underline hover:no-underline" href={`/api${path}/export?format=txt`}>Download .txt</a>
                <a className="rounded-md border border-slate-300 px-2.5 py-1 text-xs no-underline hover:no-underline" href={`/api${path}/export?format=json`}>JSON</a>
              </div>
            </div>
          </Card>
          <Card title="Verification steps"><ol className="list-decimal space-y-1 pl-5 text-sm">{fix.verification_steps.map((v: string) => <li key={v}>{v}</li>)}</ol></Card>
          {fix.issue && <Card title="Finding"><Link href={`/app/${orgId}/issues/${fix.issue.id}`}>{fix.issue.title}</Link><p className="mt-1 text-sm text-slate-500">{fix.issue.description}</p></Card>}
          <Card title="History">
            <ol className="space-y-2 text-sm" data-testid="fix-history">{fix.history.map((h: any) => (
              <li key={h.id} className="border-l-2 border-slate-200 pl-3"><StatusBadge s={h.to_status} /> <span className="text-xs text-slate-500">{fmtDate(h.created_at)}</span>
                {h.message && <div className="text-slate-600">{h.message}</div>}</li>))}</ol>
          </Card>
        </div>
      </div>
    </>
  );
}
