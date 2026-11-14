import { ExternalLink, FileText, Link2 } from "lucide-react";
import { HashValue } from "@/components/common/hash-value";
import { StatusBadge } from "@/components/common/status-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { cn } from "@/lib/utils";
import { formatDate, relativeTime } from "@/lib/format";
import { polygonExplorerLink } from "@/components/common/status-badge";

interface LedgerTransactionDetailProps {
  transaction: {
    tx_id: string;
    block_number: number;
    tx_type: string;
    entity_type: string;
    entity_id: string;
    payload_digest: string;
    prev_hash: string;
    record_hash: string;
    mode: string;
    network: string;
    status: string;
    chain_tx_hash?: string | null;
    contract_address?: string | null;
    chain_id?: number | null;
    revision?: number | null;
    timestamp: string;
  };
  rawRecord?: Record<string, unknown> | null;
  integrity?: { database_digest: string; ledger_payload_digest?: string; matches: boolean };
}

export function LedgerTransactionDetail({ transaction, rawRecord, integrity }: LedgerTransactionDetailProps) {
  const isPolygon = transaction.mode !== "simulation";
  const hasExplorerLink = isPolygon && !!transaction.chain_tx_hash;

  return (
    <Card className="space-y-3">
      <CardHeader>
        <CardTitle>Ledger transaction</CardTitle>
        <CardDescription>Details of the anchored record.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 p-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground">Mode</p>
            <p className="text-xs font-medium">{isPolygon ? "Polygon Amoy" : "Local simulation"}</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={transaction.status === "failed" ? "red" : "green"}>{titleCaseStatus(transaction.status)}</Badge>
            {hasExplorerLink && (
              <Button size="sm" variant="outline" asChild>
                <a
                  href={polygonExplorerLink(transaction.chain_tx_hash!)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs font-medium hover:text-foreground"
                >
                  <Link2 className="size-3.5" /> View on Polygon Explorer
                </a>
              </Button>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-border/60 p-3 space-y-1.5 text-xs">
          <p className="font-mono break-all">
            <span className="text-muted-foreground">Transaction hash:</span>{" "}
            <HashValue value={transaction.chain_tx_hash || transaction.tx_id} label="Transaction hash" head={16} tail={10} />
          </p>
          {transaction.contract_address && (
            <p className="font-mono break-all">
              <span className="text-muted-foreground">Contract:</span>{" "}
              <HashValue value={transaction.contract_address} label="Contract address" head={14} tail={10} />
            </p>
          )}
          <p className="font-mono break-all">
            <span className="text-muted-foreground">Chain ID:</span> {transaction.chain_id ?? "—"}
          </p>
          <p className="font-mono break-all">
            <span className="text-muted-foreground">Block number:</span> {transaction.block_number}
          </p>
          {transaction.revision != null && (
            <p className="font-mono break-all">
              <span className="text-muted-foreground">Revision:</span> {transaction.revision}
            </p>
          )}
          <p className="font-mono break-all">
            <span className="text-muted-foreground">Type:</span> {transaction.tx_type}
          </p>
          <p className="font-mono break-all">
            <span className="text-muted-foreground">Entity:</span> {transaction.entity_type} / {transaction.entity_id}
          </p>
          <p className="font-mono break-all">
            <span className="text-muted-foreground">Payload digest:</span>{" "}
            <HashValue value={transaction.payload_digest} label="Payload digest" head={16} tail={10} />
          </p>
          <p className="font-mono break-all">
            <span className="text-muted-foreground">Recorded:</span> {formatDate(transaction.timestamp)}
            <span className="ml-2 text-[10px] text-muted-foreground">({relativeTime(transaction.timestamp)})</span>
          </p>
        </div>

        {integrity && !integrity.matches && (
          <Alert variant="destructive">
            <AlertDescription>
              <FileText className="size-3 shrink-0 mr-2" />
              Database payload digest does not match the ledger record. This may indicate a data integrity issue.
            </AlertDescription>
          </Alert>
        )}

        {rawRecord && (
          <div>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Raw ledger record</p>
            <pre className="max-h-[42vh] overflow-auto rounded-lg border border-border/60 bg-background/50 p-3 font-mono text-[10px] leading-relaxed text-muted-foreground">
              {JSON.stringify(rawRecord, null, 2)}
            </pre>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function titleCaseStatus(status: string) {
  return status
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}
