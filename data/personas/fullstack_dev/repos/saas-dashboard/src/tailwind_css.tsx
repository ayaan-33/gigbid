export function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 p-6 shadow-sm dark:border-slate-800">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <div className="mt-3 text-sm text-slate-600">{children}</div>
    </section>
  );
}
