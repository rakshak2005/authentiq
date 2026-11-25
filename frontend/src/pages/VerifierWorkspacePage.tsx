import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  Copy,
  ExternalLink,
  Fingerprint,
  KeyRound,
  Lock,
  RefreshCw,
  ShieldCheck,
  ShieldQuestion,
  ShieldX,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import { BrandLogo } from "@/components/BrandLogo";
import { HashValue } from "@/components/common/hash-value";
import { LedgerBadge, StatusBadge } from "@/components/common/status-badge";
import { PageHeader, ErrorState, LoadingBlock, EmptyState } from "@/components/common/page-states";
import { SearchInput } from "@/components/common/search-input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api, extractErrorMessage, sha256File } from "@/lib/api";
import { formatDate, titleCase } from "@/lib/format";

interface PublicRecord {
  registration_reference?: string | null;
  registration_uuid?: string | null;
  title?: string | null;
  fingerprint?: string | null;
  commitment?: string | null;
  poseidon_commitment?: string | null;
  registered_at?: string | null;
  status?: string | null;
  ledger_mode?: string | null;
  ledger_tx_id?: string | null;
  asset_type?: string | null;
  privacy?: string | null;
  organization?: string | null;
}

interface LookupResponse {
  registration_reference: string;
  registration_uuid: string;
  title?: string | null;
  fingerprint: string;
  commitment: string;
  poseidon_commitment: string;
  registered_at?: string | null;
  status: string;
  ledger_mode: string;
  ledger_tx_id?: string | null;
  asset_type: string;
  privacy: string;
  organization?: string | null;
  note: string;
}

interface VerifyResponse {
  valid: boolean;
  result?: string;
  message: string;
  registration_reference: string;
  verified_at?: string | null;
  statement: string;
}

interface VerifierState {
  step: "lookup" | "challenge" | "proof" | "result";
}

export default function VerifierWorkspacePage() {
  const [params] = useSearchParams();
  const [query, setQuery] = useState(params.get("ref") || params.get("id") || "");
  const [packageText, setPackageText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [localHash, setLocalHash] = useState<string | null>(null);
  const [hashing, setHashing] = useState(false);
  const [challenge, setChallenge] = useState<{
    challenge_id: string;
    nonce: string;
    expires_at: string;
    registration_id: string;
    fingerprint: string;
    commitment: string;
    proof_system: string;
    statement: string;
  } | null>(null);
  const [record, setRecord] = useState<PublicRecord | null>(null);
  const [result, setResult] = useState<VerifyResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recordQuery = useQuery({
    queryKey: ["verifier-record", query],
    queryFn: () => api.publicGet<LookupResponse>(`/public/verify/anonymous/lookup/${query}`),
    enabled: !!query,
    retry: false,
  });

  if (recordQuery.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title="VERIFIER WORKSPACE" description="Independently verify ownership without accessing original assets." />
        <LoadingBlock rows={6} />
      </div>
    );
  }

  if (recordQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader title="VERIFIER WORKSPACE" description="Independently verify ownership without accessing original assets." />
        <ErrorState error={recordQuery.error} onRetry={() => recordQuery.refetch()} />
      </div>
    );
  }

  const lookupRecord = recordQuery.data;
  const alreadyVerified = result?.valid === true;
  const fingerprintMatches = !!record && !!localHash && localHash === record.fingerprint;

  const submitProof = async () => {
    if (!challenge || !challenge.nonce) {
      toast.error("No active challenge. Request one first.");
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(packageText);
    } catch {
      toast.error("The proof package is not valid JSON");
      return;
    }
    setBusy(true);
    try {
      const response = await api.publicPost<VerifyResponse>("/public/verify/anonymous/verify", {
        challenge_id: challenge.challenge_id,
        proof: parsed as Record<string, unknown>,
      });
      setResult(response);
      if (response.valid) toast.success("Ownership proof verified");
      else toast.error(response.message);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const readFile = async (file: File | null) => {
    if (!file) return;
    setHashing(true);
    try {
      const hash = await sha256File(file);
      setLocalHash(hash);
      setFile(file);
      toast.success("File hash computed locally");
    } catch {
      setLocalHash(null);
      toast.error("The file could not be read");
    } finally {
      setHashing(false);
    }
  };

  const requestChallenge = async () => {
    if (!record) return;
    setBusy(true);
    try {
      const response = await api.publicPost<{
        challenge_id: string;
        nonce: string;
        expires_at: string;
        registration_id: string;
        fingerprint: string;
        commitment: string;
        proof_system: string;
        statement: string;
      }>("/public/verify/anonymous/challenge", {
        registration_id: record.registration_reference,
        file_sha256: record.fingerprint,
      });
      setChallenge(response);
      setResult(null);
      toast.success("One-time challenge issued");
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-foreground text-foreground">
      <div className="pointer-events-none absolute inset-0 -z-0 grid-bg opacity-40" />
      <div className="pointer-events-none absolute -left-24 top-0 -z-0 size-[420px] rounded-full bg-blue-600/15 blur-3xl" />
      <div className="pointer-events-none absolute -right-24 bottom-0 -z-0 size-[420px] rounded-full bg-violet-600/15 blur-3xl" />

      <div className="relative z-10 mx-auto flex min-h-screen w-full max-w-5xl flex-col px-4 py-8 md:px-8">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <Link to="/" className="flex items-center gap-2.5">
            <BrandLogo className="size-10 rounded-xl shadow-lg ring-1 ring-white/10" />
            <span>
              <span className="block text-sm font-semibold tracking-[0.2em]">AUTHENTIQ</span>
              <span className="block text-[10px] uppercase tracking-[0.16em] text-muted-foreground">Verifier workspace</span>
            </span>
          </Link>
          <Button asChild variant="outline" size="sm" className="border-border bg-card text-foreground hover:bg-card">
            <Link to="/login">Sign in <ArrowRight /></Link>
          </Button>
        </header>

        <main className="mt-10 flex-1">
          {/* Lookup / search step */}
          <div className="rounded-xl border border-border/60 bg-background/40 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <SearchInput
                value={query}
                onChange={setQuery}
                placeholder="Enter registration reference or verification ID"
                className="w-80"
              />
              <div className="flex items-center gap-2">
                <p className="text-[11px] text-muted-foreground">
                  Enter a registration reference ({record?.registration_reference ? record.registration_reference : "…"}) or a verification link ID to begin.
                </p>
              </div>
            </div>
          </div>

          {/* Record display */}
          {record && (
            <div className="mt-6 grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
              <div className="space-y-4">
                <Card className="border-border bg-card">
                  <CardHeader>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="violet">{titleCase(record.privacy)}</Badge>
                      <StatusBadge status={record.status} />
                      {record.ledger_mode && <LedgerBadge mode={record.ledger_mode} />}
                    </div>
                    <CardTitle className="mt-2 text-foreground">
                      {record.title || record.registration_reference}
                    </CardTitle>
                    <CardDescription className="text-muted-foreground">
                      Public record fields only. No original file, private witness, or personal identity is disclosed.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="rounded-lg border border-border bg-muted/40 py-3">
                      <div className="flex items-center justify-center">
                        <OwnershipDnaInline value={record.fingerprint || ""} size={112} label="Public ownership DNA" />
                      </div>
                    </div>
                    <div className="rounded-lg border border-border bg-muted/50 p-3">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Public record</p>
                      <div className="mt-2 space-y-2 text-xs">
                        {record.registration_reference && (
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-muted-foreground">Reference</span>
                            <code className="font-mono text-foreground">{record.registration_reference}</code>
                          </div>
                        )}
                        {record.registered_at && (
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-muted-foreground">Registered</span>
                            <span className="text-foreground">{formatDate(record.registered_at)}</span>
                          </div>
                        )}
                        {record.fingerprint && (
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-muted-foreground">SHA-256</span>
                            <HashValue value={record.fingerprint} label="Public fingerprint" head={16} tail={12} />
                          </div>
                        )}
                        {record.commitment && (
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-muted-foreground">Commitment</span>
                            <HashValue value={record.commitment} label="Commitment" head={16} tail={12} />
                          </div>
                        )}
                        {record.ledger_tx_id && (
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-muted-foreground">Ledger transaction</span>
                            <div className="flex items-center gap-1">
                              <HashValue value={record.ledger_tx_id} label="Ledger transaction" head={14} tail={10} />
                              {record.ledger_mode === "polygon" && (
                                <a
                                  href={`https://amoy.polygonscan.com/tx/${record.ledger_tx_id}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="size-6 shrink-0 rounded border border-border/60 bg-muted/40 text-[10px] text-violet hover:bg-violet/20 hover:text-violet"
                                  title="View on Polygon Amoy Explorer"
                                >
                                  <ExternalLink className="size-3.5" />
                                </a>
                              )}
                            </div>
                          </div>
                        )}
                        {record.organization && (
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-muted-foreground">Organization</span>
                            <span className="text-foreground">{record.organization}</span>
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="space-y-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Step 1 — Match the original file</p>
                      <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-muted/40 px-4 py-4 text-xs text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground">
                        <Upload className="size-4" />
                        {file ? <span>Change file</span> : <span>Load original file</span>}
                        <input type="file" className="hidden" onChange={(event) => readFile(event.target.files?.[0] || null)} />
                      </label>
                      {hashing && <p className="mt-1 text-[11px] text-muted-foreground">Computing SHA-256 in your browser...</p>}
                      {localHash && (
                        <div className={cn("rounded-lg border p-3 mt-2", fingerprintMatches ? "border-foreground/25 bg-accent/15" : "border-foreground/25 bg-red-500/5")}>
                          <div className="flex items-center gap-2">
                            {fingerprintMatches ? (
                              <> <CheckCircle2 className="size-4 text-foreground" /> Fingerprint matches the registered record</>
                            ) : (
                              <> <ShieldX className="size-4 text-destructive" /> Fingerprint does not match</>
                            )}
                          </div>
                          <HashValue value={localHash} label="Local SHA-256" head={18} tail={12} />
                          {!fingerprintMatches && (
                            <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
                              A different file cannot prove ownership of this record. This check is enforced by the server.
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>

                <div className="space-y-2">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Step 2 — Request a challenge</p>
                  <Button
                    onClick={requestChallenge}
                    loading={busy}
                    disabled={!record || !fingerprintMatches}
                    className="w-full"
                  >
                    <RefreshCw /> {challenge ? "New challenge" : "Request one-time challenge"}
                  </Button>
                  {challenge && (
                    <div className="mt-3 rounded-lg border border-foreground/20 bg-blue-500/5 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-muted-foreground">Challenge active</span>
                        <span className="text-[10px] text-muted-foreground">Expires {formatDate(challenge.expires_at, "MMM d, HH:mm:ss")}</span>
                      </div>
                      <div className="mt-2"><HashValue value={challenge.nonce} label="Challenge nonce" head={18} tail={12} /></div>
                      <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground">
                        Challenges are single-use. Requesting a new nonce invalidates prior unused challenges.
                      </p>
                    </div>
                  )}
                  {error && (
                    <Alert variant="destructive">
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}
                </div>
              </div>

              <div className="space-y-4">
                <Card className="border-border bg-card">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-sm text-foreground">
                      <ShieldCheck className="size-4 text-foreground" /> Submit proof package
                    </CardTitle>
                    <CardDescription className="text-muted-foreground">
                      Paste the AUTHENTIQ-VERIFICATION-PACKAGE-V1 JSON generated by the owner or your own prover.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <Textarea
                      value={packageText}
                      onChange={(event) => setPackageText(event.target.value)}
                      className="min-h-[150px] border-border bg-muted/50 font-mono text-[10px] text-muted-foreground"
                      placeholder="Paste proof package JSON here"
                    />
                    <Button
                      onClick={submitProof}
                      loading={busy}
                      disabled={!packageText.trim() || !challenge}
                      className="w-full"
                    >
                      {challenge ? (
                        <>
                          <ShieldCheck /> Verify proof
                        </>
                      ) : (
                        <>
                          <RefreshCw /> Request challenge first
                        </>
                      )}
                    </Button>
                  </CardContent>
                </Card>

                {result && (
                  <div className={`rounded-lg border p-4 ${result.valid ? "border-foreground/25 bg-accent/25" : "border-foreground/30 bg-foreground/5"}`}>
                    <div className="flex items-center gap-2">
                      {result.valid ? (
                        <CheckCircle2 className="size-5 text-foreground" />
                      ) : (
                        <ShieldX className="size-5 text-destructive" />
                      )}
                      <p className={`text-sm font-semibold ${result.valid ? "text-foreground" : "text-destructive"}`}>
                        {result.valid ? "Ownership proof verified" : "Proof rejected"}
                      </p>
                    </div>
                    <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{result.message}</p>
                    {result.statement && (
                      <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">{result.statement}</p>
                    )}
                    {result.verified_at && (
                      <p className="mt-1 text-[10px] text-foreground">
                        Verified {formatDate(result.verified_at)}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </main>

        <footer className="mt-10 border-t border-border pt-4 text-[10px] text-muted-foreground">
          AUTHENTIQ verifier workspace · No original file, private witness, or personal identity is exposed by this page.
        </footer>
      </div>
    </div>
  );
}

function OwnershipDnaInline({ value, size, label }: { value: string; size: number; label: string }) {
  const chars = value.slice(0, 64);
  const cellCount = 49; // 7x7 grid
  const cells: { hex: string; color: string }[] = [];
  for (let i = 0; i < cellCount; i++) {
    const hex = chars.charCodeAt(i % chars.length).toString(16);
    const brightness = parseInt(hex, 16) / 15;
    const color = `hsl(200, 60%, ${Math.round(20 + brightness * 50)}%)`;
    cells.push({ hex, color });
  }
  const cellSize = Math.floor(size / 7);
  return (
    <div className="flex flex-wrap items-center justify-center gap-[1px]">
      {cells.map((cell, i) => (
        <div
          key={i}
          className={`w-[${cellSize}px] h-[${cellSize}px] rounded-sm`}
          style={{ backgroundColor: cell.color }}
        />
      ))}
    </div>
  );
}

function cn(...classes: (string | boolean | undefined | null)[]) {
  return classes.filter(Boolean).join(" ");
}
