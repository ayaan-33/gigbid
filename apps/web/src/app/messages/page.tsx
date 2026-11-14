"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, ok } from "@/lib/api/client";
import { useData } from "@/lib/hooks";
import { ApprovalPanel } from "@/components/ApprovalPanel";
import { Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";

type Any = Record<string, unknown>;

function Messages() {
  const sp = useSearchParams();
  const router = useRouter();
  const sel = sp.get("c");
  const list = useData(async () => ok(await api.GET("/api/messages")), [], 10000);
  const conv = useData(
    async () => (sel ? ok(await api.GET("/api/messages/{conversation_id}", { params: { path: { conversation_id: sel } } })) : null),
    [sel],
    sel ? 6000 : undefined,
  );
  const pending = (conv.data?.pending ?? null) as Any | null;
  const reply = (pending?.reply ?? {}) as Any;
  const [override, setText] = useState<{ for: string; text: string } | null>(null);
  const text = override && override.for === String(reply.text ?? "") ? override.text : String(reply.text ?? "");

  return (
    <>
      <PageHeader title="Messages" sub="Client threads with suggested replies and interview slots. You approve before anything is sent." />
      {list.error && <ErrorBox error={list.error} onRetry={list.refresh} />}
      <div className="grid gap-4 md:grid-cols-3">
        <nav aria-label="Conversations" className="space-y-2">
          {list.loading && !list.data && <Spinner />}
          {list.data?.length === 0 && <Empty title="No conversations">Client replies appear here.</Empty>}
          {list.data?.map((c) => (
            <button
              key={c.conversation_id}
              onClick={() => router.push(`/messages?c=${c.conversation_id}`)}
              aria-current={sel === c.conversation_id ? "true" : undefined}
              className={`card w-full text-left text-sm ${sel === c.conversation_id ? "border-brand" : ""}`}
            >
              <p className="font-medium">{c.job_id ?? c.conversation_id}</p>
              <p className="text-xs text-muted">{c.state}</p>
            </button>
          ))}
        </nav>
        <section className="space-y-4 md:col-span-2" aria-live="polite">
          {!sel && <Empty title="Pick a conversation" />}
          {sel && conv.loading && !conv.data && <Spinner />}
          {conv.data && (
            <>
              <div className="card space-y-3">
                {(conv.data.messages ?? []).map((m) => (
                  <div key={m.id as string} className={`flex ${m.sender === "freelancer" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${m.sender === "freelancer" ? "bg-brand/10" : "bg-line/50"}`}>
                      <p className="label mb-0.5">{m.sender as string}</p>
                      <p className="whitespace-pre-wrap">{m.text as string}</p>
                    </div>
                  </div>
                ))}
                {!pending && (
                  <button
                    className="btn-ghost"
                    onClick={async () => {
                      await api.POST("/api/messages/{conversation_id}/draft", { params: { path: { conversation_id: sel! } } });
                      setTimeout(conv.refresh, 2000);
                    }}
                  >
                    Draft a reply
                  </button>
                )}
              </div>
              {pending && (
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="card space-y-2">
                    <p className="label">Suggested reply · intent {String((pending.intent as Any)?.intent)}</p>
                    <textarea className="input min-h-40 text-sm" aria-label="Reply text" value={text} onChange={(e) => setText({ for: String(reply.text ?? ""), text: e.target.value })} />
                    {((reply.proposed_slots as Any[]) ?? []).length > 0 && (
                      <p className="text-xs text-muted">
                        Interview slots: {(reply.proposed_slots as Any[]).map((s) => String(s.start).slice(0, 16).replace("T", " ")).join(" · ")} (UTC)
                      </p>
                    )}
                    {((pending.evidence as Any[]) ?? []).length > 0 && (
                      <ul className="text-xs text-muted">
                        {(pending.evidence as Any[]).map((e) => (
                          <li key={String(e.id)}>
                            [{String(e.id)}] {String(e.snippet).slice(0, 120)}…
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <ApprovalPanel
                    kind="message"
                    threadId={conv.data.thread_id!}
                    dryRun={(pending.dry_run ?? {}) as Any}
                    editedText={text}
                    dirty={text.trim() !== String(reply.text ?? "").trim()}
                    onDone={() => setTimeout(conv.refresh, 2500)}
                  />
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </>
  );
}

export default function MessagesPage() {
  return (
    <Suspense>
      <Messages />
    </Suspense>
  );
}
