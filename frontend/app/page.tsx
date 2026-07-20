import { fetchHealth, healthLabel } from "@/lib/health";

export default async function Home() {
  const health = await fetchHealth();
  const online = health?.status === "ok";

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl items-center px-6 py-16">
      <section className="w-full rounded-2xl border border-zinc-800 bg-zinc-900 p-8 shadow-2xl">
        <p className="text-sm font-semibold uppercase tracking-[0.25em] text-red-400">BOUNDARY</p>
        <h1 className="mt-3 text-4xl font-bold">AMD DevMaster Track 2</h1>
        <p className="mt-3 text-zinc-400">Private, local-first agent development workspace.</p>
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          <article className="rounded-xl border border-zinc-700 bg-zinc-950 p-5">
            <div className="flex items-center gap-3">
              <span className={`h-3 w-3 rounded-full ${online ? "bg-emerald-400" : "bg-amber-400"}`} />
              <h2 className="font-semibold">{healthLabel(health)}</h2>
            </div>
            <p className="mt-2 text-sm text-zinc-500">{online ? "Health checks are passing." : "Start the FastAPI service to connect."}</p>
          </article>
          <article className="rounded-xl border border-zinc-700 bg-zinc-950 p-5">
            <h2 className="font-semibold">Model: not configured</h2>
            <p className="mt-2 text-sm text-zinc-500">No remote APIs or credentials are enabled.</p>
          </article>
        </div>
      </section>
    </main>
  );
}
