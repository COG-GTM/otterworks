import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  DollarSign,
  Download,
  Percent,
  Ship,
  TrendingUp,
} from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AppShell } from "@/components/layout/app-shell";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { marginsApi } from "@/lib/api";
import type { MarginRow } from "@/lib/api";

const CHART_FROM_DAYS = 180;

const TOOLTIP_STYLE = {
  backgroundColor: "#18233a",
  border: "1px solid #24324b",
  color: "#e2e8f0",
};

function chartFromDate(): string {
  const d = new Date();
  d.setDate(d.getDate() - CHART_FROM_DAYS);
  return d.toISOString().slice(0, 10);
}

export default function MarginsPage() {
  return (
    <AppShell>
      <ErrorBoundary>
        <MarginsContent />
      </ErrorBoundary>
    </AppShell>
  );
}

type SortKey = keyof Pick<
  MarginRow,
  "sku" | "name" | "category" | "supplier" | "listPriceUsd" | "cogsUsd" | "marginPct"
>;

function MarginsContent() {
  const {
    data: margins,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["margins", "dashboard"],
    queryFn: () => marginsApi.getMargins(),
  });

  const { data: salmonPrices } = useQuery({
    queryKey: ["margins", "salmon-prices"],
    queryFn: () => marginsApi.getMarketPrices("SALMON_NOK_KG", chartFromDate()),
  });

  const { data: freightPrices } = useQuery({
    queryKey: ["margins", "freight-prices"],
    queryFn: () => marginsApi.getMarketPrices("DREWRY_WCI_USD_FEU", chartFromDate()),
  });

  const { data: marginSeries } = useQuery({
    queryKey: ["margins", "series"],
    queryFn: () => marginsApi.getMarginSeries({ from: chartFromDate() }),
  });

  const [filter, setFilter] = useState("");
  const [category, setCategory] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("sku");
  const [sortAsc, setSortAsc] = useState(true);

  const categories = useMemo(
    () => Array.from(new Set(margins?.rows.map((r) => r.category) ?? [])).sort(),
    [margins],
  );

  const visibleRows = useMemo(() => {
    const term = filter.trim().toLowerCase();
    const rows = (margins?.rows ?? []).filter(
      (r) =>
        (category === "all" || r.category === category) &&
        (term === "" ||
          r.sku.toLowerCase().includes(term) ||
          r.name.toLowerCase().includes(term) ||
          r.supplier.toLowerCase().includes(term)),
    );
    const sorted = [...rows].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      const cmp =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv));
      return sortAsc ? cmp : -cmp;
    });
    return sorted;
  }, [margins, filter, category, sortKey, sortAsc]);

  const commodityChartData = useMemo(() => {
    const byDate = new Map<string, { date: string; salmon?: number; freight?: number }>();
    for (const p of salmonPrices?.prices ?? []) {
      byDate.set(p.priceDate, { ...(byDate.get(p.priceDate) ?? { date: p.priceDate }), salmon: p.value });
    }
    for (const p of freightPrices?.prices ?? []) {
      byDate.set(p.priceDate, { ...(byDate.get(p.priceDate) ?? { date: p.priceDate }), freight: p.value });
    }
    return Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
  }, [salmonPrices, freightPrices]);

  const marginChartData = useMemo(
    () =>
      (marginSeries?.points ?? []).map((p) => ({
        date: p.marginDate,
        marginPct: p.marginPct,
      })),
    [marginSeries],
  );

  const onSort = (key: SortKey) => {
    if (key === sortKey) setSortAsc((v) => !v);
    else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const onExportCsv = async () => {
    try {
      const csv = await marginsApi.exportCsv();
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `sku-margins-${margins?.asOfDate ?? "export"}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      toast.success("Margins CSV exported");
    } catch {
      toast.error("CSV export failed. Please try again.");
    }
  };

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto space-y-6" data-testid="margins-loading">
        <div className="h-8 w-64 bg-surface-raised rounded animate-pulse" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-surface-raised border border-line rounded-xl animate-pulse" />
          ))}
        </div>
        <div className="h-72 bg-surface-raised border border-line rounded-xl animate-pulse" />
        <div className="h-96 bg-surface-raised border border-line rounded-xl animate-pulse" />
      </div>
    );
  }

  if (isError || !margins) {
    return (
      <div className="max-w-7xl mx-auto" data-testid="margins-error">
        <div className="bg-surface border border-line rounded-xl p-10 text-center">
          <h1 className="text-lg font-semibold text-slate-100">
            Margins data is unavailable
          </h1>
          <p className="text-sm text-slate-400 mt-2">
            We couldn&apos;t load the margins dashboard. Please try again.
          </p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-otter-500 text-white rounded-lg hover:bg-otter-400 transition text-sm font-medium"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const sourceLive = margins.source !== "synthetic";

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Margins</h1>
          <p className="text-sm text-slate-400 mt-1" data-testid="margins-caption">
            Data as of {margins.asOfDate}
            {margins.lastSyncAt ? ` (${margins.lastSyncAt})` : ""} — Source: Trading
            Economics (manual pull)
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            data-testid="source-badge"
            className={`px-2.5 py-1 rounded-full text-xs font-medium border ${
              sourceLive
                ? "bg-green-500/10 text-green-300 border-green-500/30"
                : "bg-surface-raised text-slate-300 border-line"
            }`}
          >
            {sourceLive ? "live" : "synthetic"}
          </span>
          <button
            onClick={onExportCsv}
            className="flex items-center gap-2 px-4 py-2 bg-surface-raised text-slate-300 border border-line rounded-lg hover:bg-surface-hover hover:border-line-strong hover:text-slate-100 transition text-sm font-medium"
          >
            <Download size={16} />
            Export CSV
          </button>
        </div>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiTile
          icon={Percent}
          label="Gross Margin %"
          value={`${margins.kpis.grossMarginPct.toFixed(1)}%`}
          color="green"
        />
        <KpiTile
          icon={DollarSign}
          label="COGS / unit"
          value={`$${margins.kpis.avgCogsUsd.toFixed(2)}`}
          color="blue"
        />
        <KpiTile
          icon={TrendingUp}
          label="Salmon Index"
          value={`${margins.kpis.salmonIndex.toFixed(2)} NOK/kg`}
          color="orange"
        />
        <KpiTile
          icon={Ship}
          label="Freight Index"
          value={`$${margins.kpis.freightIndex.toFixed(0)}/FEU`}
          color="purple"
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-surface rounded-xl border border-line p-5" data-testid="commodity-chart">
          <h2 className="text-sm font-semibold text-slate-300 mb-3">
            Commodity &amp; freight prices ({CHART_FROM_DAYS}d)
          </h2>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={commodityChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#24324b" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} stroke="#94a3b8" minTickGap={40} />
              <YAxis yAxisId="salmon" tick={{ fontSize: 11, fill: "#94a3b8" }} stroke="#94a3b8" />
              <YAxis yAxisId="freight" orientation="right" tick={{ fontSize: 11, fill: "#94a3b8" }} stroke="#94a3b8" />
              <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#e2e8f0" }} />
              <Legend wrapperStyle={{ color: "#cbd5e1" }} />
              <Line
                yAxisId="salmon"
                type="monotone"
                dataKey="salmon"
                name="Salmon (NOK/kg)"
                stroke="#fb923c"
                dot={false}
                strokeWidth={1.5}
              />
              <Line
                yAxisId="freight"
                type="monotone"
                dataKey="freight"
                name="Freight (USD/FEU)"
                stroke="#a78bfa"
                dot={false}
                strokeWidth={1.5}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="bg-surface rounded-xl border border-line p-5" data-testid="margin-chart">
          <h2 className="text-sm font-semibold text-slate-300 mb-3">
            Average margin % ({CHART_FROM_DAYS}d)
          </h2>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={marginChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#24324b" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#94a3b8" }} stroke="#94a3b8" minTickGap={40} />
              <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} stroke="#94a3b8" domain={["auto", "auto"]} />
              <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#e2e8f0" }} />
              <Legend wrapperStyle={{ color: "#cbd5e1" }} />
              <Line
                type="monotone"
                dataKey="marginPct"
                name="Avg margin %"
                stroke="#4ade80"
                dot={false}
                strokeWidth={1.5}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* SKU margins grid */}
      <div className="bg-surface rounded-xl border border-line">
        <div className="flex items-center justify-between gap-3 flex-wrap p-4 border-b border-line">
          <h2 className="text-sm font-semibold text-slate-300">
            SKU profitability ({visibleRows.length} of {margins.rows.length})
          </h2>
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Filter by SKU, name, supplier…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="px-3 py-1.5 bg-surface-raised text-slate-100 placeholder:text-slate-500 border border-line rounded-lg text-sm w-64 hover:border-line-strong focus:outline-none focus:ring-2 focus:ring-otter-400"
              data-testid="grid-filter"
            />
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="px-3 py-1.5 border border-line rounded-lg text-sm bg-surface-raised text-slate-100 hover:border-line-strong focus:outline-none focus:ring-2 focus:ring-otter-400"
              data-testid="category-filter"
            >
              <option value="all">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="margins-grid">
            <thead>
              <tr className="text-left text-xs text-slate-400 border-b border-line bg-surface-raised">
                <SortableTh label="SKU" active={sortKey === "sku"} asc={sortAsc} onClick={() => onSort("sku")} />
                <SortableTh label="Product" active={sortKey === "name"} asc={sortAsc} onClick={() => onSort("name")} />
                <SortableTh label="Category" active={sortKey === "category"} asc={sortAsc} onClick={() => onSort("category")} />
                <SortableTh label="Supplier" active={sortKey === "supplier"} asc={sortAsc} onClick={() => onSort("supplier")} />
                <SortableTh label="List Price" active={sortKey === "listPriceUsd"} asc={sortAsc} onClick={() => onSort("listPriceUsd")} right />
                <SortableTh label="COGS" active={sortKey === "cogsUsd"} asc={sortAsc} onClick={() => onSort("cogsUsd")} right />
                <SortableTh label="Margin %" active={sortKey === "marginPct"} asc={sortAsc} onClick={() => onSort("marginPct")} right />
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => (
                <tr key={row.sku} className="border-b border-line hover:bg-surface-raised">
                  <td className="px-4 py-2.5 font-medium text-slate-100">{row.sku}</td>
                  <td className="px-4 py-2.5 text-slate-300">{row.name}</td>
                  <td className="px-4 py-2.5 text-slate-400">{row.category}</td>
                  <td className="px-4 py-2.5 text-slate-400">{row.supplier}</td>
                  <td className="px-4 py-2.5 text-right text-slate-300">
                    ${row.listPriceUsd.toFixed(2)}
                  </td>
                  <td className="px-4 py-2.5 text-right text-slate-300">
                    ${row.cogsUsd.toFixed(2)}
                  </td>
                  <td
                    className={`px-4 py-2.5 text-right font-medium ${
                      row.marginPct < 0
                        ? "text-red-400"
                        : row.marginPct < 20
                          ? "text-orange-400"
                          : "text-green-400"
                    }`}
                  >
                    {row.marginPct.toFixed(1)}%
                  </td>
                </tr>
              ))}
              {visibleRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-400">
                    No SKUs match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function KpiTile({
  icon: Icon,
  label,
  value,
  color,
}: Readonly<{
  icon: typeof Percent;
  label: string;
  value: string;
  color: "blue" | "purple" | "green" | "orange";
}>) {
  const colorClasses = {
    blue: "bg-blue-500/10 text-blue-400",
    purple: "bg-purple-500/10 text-purple-400",
    green: "bg-green-500/10 text-green-400",
    orange: "bg-orange-500/10 text-orange-400",
  };

  return (
    <div className="bg-surface rounded-xl border border-line p-5" data-testid={`kpi-${label}`}>
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${colorClasses[color]}`}>
          <Icon size={20} />
        </div>
        <div>
          <p className="text-2xl font-bold text-slate-100">{value}</p>
          <p className="text-xs text-slate-400">{label}</p>
        </div>
      </div>
    </div>
  );
}

function SortableTh({
  label,
  active,
  asc,
  onClick,
  right,
}: Readonly<{
  label: string;
  active: boolean;
  asc: boolean;
  onClick: () => void;
  right?: boolean;
}>) {
  let SortIcon = ArrowUpDown;
  if (active) SortIcon = asc ? ArrowUp : ArrowDown;
  return (
    <th className={`px-4 py-2.5 font-medium ${right ? "text-right" : ""}`}>
      <button
        onClick={onClick}
        className={`inline-flex items-center gap-1 hover:text-slate-100 ${active ? "text-slate-100" : ""}`}
      >
        {label}
        <SortIcon size={12} />
      </button>
    </th>
  );
}
