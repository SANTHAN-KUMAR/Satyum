/** A vertical progress stepper — monochrome with a gradient highlight on the active/done steps. */
export function Stepper({ steps, current }: { steps: { title: string; sub: string }[]; current: number }) {
  return (
    <ol className="space-y-1">
      {steps.map((s, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={s.title} className="flex gap-3.5">
            <div className="flex flex-col items-center">
              <span
                className={
                  "flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold transition " +
                  (done
                    ? "bg-ink text-white"
                    : active
                      ? "gradient-accent text-white shadow-card"
                      : "border border-hairline bg-white/70 text-slate-500")
                }
                aria-hidden
              >
                {done ? "✓" : i + 1}
              </span>
              {i < steps.length - 1 && (
                <span className={"my-1 w-px flex-1 " + (done ? "gradient-accent" : "bg-hairline")} />
              )}
            </div>
            <div className={"pb-7 " + (active || done ? "" : "opacity-60")}>
              <p className={"text-sm font-semibold " + (active || done ? "text-slate-100" : "text-slate-400")}>
                {s.title}
              </p>
              <p className="text-xs text-slate-500">{s.sub}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
