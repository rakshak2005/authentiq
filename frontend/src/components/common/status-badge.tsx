import { Badge } from "@/components/ui/badge";
import { statusTone, titleCase } from "@/lib/format";
import { api } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

export function StatusBadge({ status, className }: { status?: string | null; className?: string }) {
  const tone = (status && statusTone[status]) || "slate";
  return (
    <Badge variant={tone as "green" | "blue" | "amber" | "red" | "violet" | "slate"} className={className}>
      <span className="size-1.5 rounded-full bg-current opacity-80" />
      {titleCase(status || "unknown")}
    </Badge>
  );
}

export function LedgerBadge({ mode, network }: { mode?: string | null; network?: string | null }) {
  const simulated = !mode || mode === "simulation";
  return (
    <Badge variant={simulated ? "amber" : "violet"} title={network || undefined}>
      {simulated ? "Simulated ledger" : "Polygon Amoy"}
    </Badge>
  );
}

export function LedgerStatusIndicator({ mode, connected, available, errors }: { mode?: string | null; connected?: boolean | null; available?: boolean | null; errors?: string[] | null }) {
  const { data: status } = useQuery({
    queryKey: ["ledger-status"],
    queryFn: () => api.get<{ mode?: string; connected?: boolean; available?: boolean; errors?: string[] }>("/ledger/status"),
    staleTime: 30000,
  });

  const m = mode ?? status?.mode ?? "simulation";
  const simulated = !m || m === "simulation";
  const c = connected ?? status?.connected ?? false;
  const av = available ?? status?.available ?? true;
  const errs = errors ?? status?.errors ?? [];

  if (simulated) {
    return (
      <Badge variant="amber" title="Local append-only simulation ledger">
        Simulated ledger
      </Badge>
    );
  }
  if (!av || !c) {
    return (
      <Badge variant="red" title={errs.join("; ") || "Polygon Amoy unavailable"}>
        Polygon unavailable
      </Badge>
    );
  }
  return (
    <Badge variant="green" title="Polygon Amoy connected">
      Polygon Amoy connected
    </Badge>
  );
}

export function LedgerAnchoringStatus({ tx, mode }: { tx: { chain_tx_hash?: string | null; status?: string | null; contract_address?: string | null; chain_id?: number | null } | null; mode?: string | null }) {
  const simulated = !mode || mode === "simulation";
  if (simulated) {
    return (
      <Badge variant="amber" title="Local append-only simulation record">
        Not anchored
      </Badge>
    );
  }
  if (!tx) {
    return (
      <Badge variant="slate" title="No ledger transaction recorded">
        Not anchored
      </Badge>
    );
  }
  if (tx.status === "failed") {
    return (
      <Badge variant="red" title="Blockchain transaction failed">
        Failed
      </Badge>
    );
  }
  if (tx.chain_tx_hash && tx.status === "confirmed") {
    return (
      <Badge variant="green" title="Confirmed on Polygon Amoy">
        Confirmed
      </Badge>
    );
  }
  return (
    <Badge variant="blue" title="Transaction submitted, awaiting confirmation">
      Submitted
    </Badge>
  );
}

export const POLYGON_AMOY_EXPLORER_URL = "https://amoy.polygonscan.com";

export function polygonExplorerLink(txHash: string) {
  return `${POLYGON_AMOY_EXPLORER_URL}/tx/${txHash}`;
}
