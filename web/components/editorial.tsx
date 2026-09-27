import { cn } from "@/lib/utils";

/** Small-caps section marker. Used for every section in the evidence apparatus. */
export function Label({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("label", className)}>{children}</div>;
}

/** A hairline rule that reads as editorial, not as a border. */
export function Rule({ className }: { className?: string }) {
  return <div className={cn("h-px w-full bg-rule", className)} />;
}

/**
 * The decision id, set in mono so it reads as a citation rather than as prose.
 * This is the visual atom of the whole product: every claim carries one.
 */
export function DecisionId({ id, className }: { id: string; className?: string }) {
  return (
    <span className={cn("font-mono text-[12.5px] tracking-tight text-ink-soft", className)}>{id}</span>
  );
}
