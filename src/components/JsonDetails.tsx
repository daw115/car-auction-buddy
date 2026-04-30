import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

type Props = {
  data: unknown;
  /** Max characters before a string is truncated. */
  stringLimit?: number;
  /** Max items shown for arrays/objects before "show more". */
  itemLimit?: number;
  /** Initial collapsed depth — nodes deeper than this start collapsed. */
  collapseDepth?: number;
};

export function JsonDetails({
  data,
  stringLimit = 200,
  itemLimit = 10,
  collapseDepth = 2,
}: Props) {
  return (
    <div className="border-t border-border/50 bg-muted/30 px-2 py-1.5 font-mono text-[10px] leading-tight">
      <Node value={data} depth={0} stringLimit={stringLimit} itemLimit={itemLimit} collapseDepth={collapseDepth} />
    </div>
  );
}

function Node({
  value,
  depth,
  stringLimit,
  itemLimit,
  collapseDepth,
  keyLabel,
}: {
  value: unknown;
  depth: number;
  stringLimit: number;
  itemLimit: number;
  collapseDepth: number;
  keyLabel?: string;
}) {
  if (value === null) return <Line keyLabel={keyLabel}><span className="text-muted-foreground">null</span></Line>;
  if (value === undefined) return <Line keyLabel={keyLabel}><span className="text-muted-foreground">undefined</span></Line>;

  const t = typeof value;
  if (t === "string") return <StringNode keyLabel={keyLabel} value={value as string} limit={stringLimit} />;
  if (t === "number" || t === "boolean" || t === "bigint")
    return (
      <Line keyLabel={keyLabel}>
        <span className="text-foreground">{String(value)}</span>
      </Line>
    );

  if (Array.isArray(value)) {
    return (
      <CollectionNode
        keyLabel={keyLabel}
        entries={value.map((v, i) => [String(i), v] as const)}
        open={"["}
        close={"]"}
        depth={depth}
        stringLimit={stringLimit}
        itemLimit={itemLimit}
        collapseDepth={collapseDepth}
        size={value.length}
        kind="array"
      />
    );
  }

  if (t === "object") {
    const obj = value as Record<string, unknown>;
    const entries = Object.entries(obj);
    return (
      <CollectionNode
        keyLabel={keyLabel}
        entries={entries}
        open={"{"}
        close={"}"}
        depth={depth}
        stringLimit={stringLimit}
        itemLimit={itemLimit}
        collapseDepth={collapseDepth}
        size={entries.length}
        kind="object"
      />
    );
  }

  return <Line keyLabel={keyLabel}>{String(value)}</Line>;
}

function Line({ keyLabel, children }: { keyLabel?: string; children: React.ReactNode }) {
  return (
    <div className="whitespace-pre-wrap break-words pl-4">
      {keyLabel !== undefined && <span className="text-primary">{keyLabel}: </span>}
      {children}
    </div>
  );
}

function StringNode({ keyLabel, value, limit }: { keyLabel?: string; value: string; limit: number }) {
  const [expanded, setExpanded] = useState(false);
  const tooLong = value.length > limit;
  const shown = !tooLong || expanded ? value : value.slice(0, limit);
  return (
    <div className="whitespace-pre-wrap break-words pl-4">
      {keyLabel !== undefined && <span className="text-primary">{keyLabel}: </span>}
      <span className="text-emerald-600 dark:text-emerald-400">"{shown}{tooLong && !expanded ? "…" : ""}"</span>
      {tooLong && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((v) => !v);
          }}
          className="ml-1 text-[9px] uppercase tracking-wide text-primary hover:underline"
        >
          {expanded ? "show less" : `show more (+${value.length - limit})`}
        </button>
      )}
    </div>
  );
}

function CollectionNode({
  keyLabel,
  entries,
  open,
  close,
  depth,
  stringLimit,
  itemLimit,
  collapseDepth,
  size,
  kind,
}: {
  keyLabel?: string;
  entries: ReadonlyArray<readonly [string, unknown]>;
  open: string;
  close: string;
  depth: number;
  stringLimit: number;
  itemLimit: number;
  collapseDepth: number;
  size: number;
  kind: "array" | "object";
}) {
  const [open_, setOpen] = useState(depth < collapseDepth);
  const [showAll, setShowAll] = useState(false);

  const visible = showAll ? entries : entries.slice(0, itemLimit);
  const hidden = entries.length - visible.length;

  return (
    <div className="pl-4">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="inline-flex items-center gap-0.5 text-left hover:text-primary"
      >
        {open_ ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {keyLabel !== undefined && <span className="text-primary">{keyLabel}: </span>}
        <span className="text-muted-foreground">
          {open}
          {!open_ && (
            <span className="ml-1 text-[9px]">
              {size} {kind === "array" ? "item" : "key"}
              {size === 1 ? "" : "s"}
            </span>
          )}
          {!open_ && close}
        </span>
      </button>
      {open_ && (
        <>
          {visible.map(([k, v]) => (
            <Node
              key={k}
              keyLabel={kind === "array" ? `[${k}]` : k}
              value={v}
              depth={depth + 1}
              stringLimit={stringLimit}
              itemLimit={itemLimit}
              collapseDepth={collapseDepth}
            />
          ))}
          {hidden > 0 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setShowAll(true);
              }}
              className="ml-4 text-[9px] uppercase tracking-wide text-primary hover:underline"
            >
              show {hidden} more
            </button>
          )}
          {showAll && entries.length > itemLimit && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setShowAll(false);
              }}
              className="ml-4 text-[9px] uppercase tracking-wide text-primary hover:underline"
            >
              show less
            </button>
          )}
          <div className="pl-4 text-muted-foreground">{close}</div>
        </>
      )}
    </div>
  );
}
