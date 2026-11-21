import React, { useState, useEffect, useMemo } from "react";
import {
  Package,
  AlertTriangle,
  ArrowLeftRight,
  PauseCircle,
  Search,
  Layers,
  Filter,
  RefreshCw,
  Info,
  ChevronDown,
  ChevronUp,
  Plus,
  X,
  CheckCircle2,
} from "lucide-react";
import { loadDashboardData } from "./api/inventoryApi";

const ACTION_META = {
  ORDER: {
    label: "ORDER FROM VENDOR",
    short: "Shortage cannot be filled internally",
    badge: "bg-rose-500/15 text-rose-300 border-rose-500/30",
    dot: "bg-rose-400",
  },
  TRANSFER_IN: {
    label: "TRANSFER IN",
    short: "Shortage covered by surplus godown",
    badge: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    dot: "bg-sky-400",
  },
  TRANSFER_OUT: {
    label: "TRANSFER OUT",
    short: "Excess stock routed to deficit godown",
    badge: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    dot: "bg-amber-400",
  },
  HOLD: {
    label: "OVERSTOCK HOLD",
    short: "Stock exceeds 1.5× target — pause orders",
    badge: "bg-purple-500/15 text-purple-300 border-purple-500/30",
    dot: "bg-purple-400",
  },
  OK: {
    label: "HEALTHY",
    short: "Within lead-time safety buffer",
    badge: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    dot: "bg-emerald-400",
  },
};

const DISCRETE_UNITS = new Set(["NOS", "NO", "SET", "SETS", "PCS", "UNIT"]);
const isDiscrete = (unit) => DISCRETE_UNITS.has(String(unit || "").toUpperCase().trim());

const fmtQty = (n, unit = "") => {
  if (typeof n !== "number" || Number.isNaN(n)) return n;
  const val = isDiscrete(unit) ? Math.ceil(n) : n;
  return val.toLocaleString("en-IN", {
    maximumFractionDigits: isDiscrete(unit) ? 0 : 2,
  });
};

const getUnitBreakdown = (rows, qtyField) => {
  const byUnit = {};
  for (const r of rows) {
    const q = Number(r[qtyField]) || 0;
    if (q <= 0) continue;
    const u = String(r.unit || "UNITS").toUpperCase();
    const cleanQ = isDiscrete(u) ? Math.ceil(q) : q;
    byUnit[u] = (byUnit[u] || 0) + cleanQ;
  }
  return Object.entries(byUnit).sort((a, b) => b[1] - a[1]);
};

// Recomputes ordering & greedy inter-godown transfers for a snapshot after live stock edits
function recalculateMonthDecisions(monthRows, safetyBuffer = 0.15) {
  const updated = monthRows.map((r) => {
    const stock = Math.max(0, Number(r.stock) || 0);
    const cons = Number(r.rolling_monthly_consumption) || 0;
    const leadDays = Number(r.lead_time_days) || 30;
    const target = Number((cons * (leadDays / 30) * (1 + safetyBuffer)).toFixed(4));
    const holdThreshold = target * 1.5;

    return {
      ...r,
      stock,
      lead_time_target_stock: target,
      recommended_order_qty: 0,
      recommended_transfer_in: 0,
      recommended_transfer_out: 0,
      recommended_hold_qty: 0,
      action: "OK",
      _surplus: r.godown === "KANPUR CLOSER" ? 0 : Math.max(0, stock - holdThreshold),
      _deficit: r.godown === "KANPUR CLOSER" ? 0 : Math.max(0, target - stock),
    };
  });

  const newTransfers = [];
  const byItem = {};
  for (const row of updated) {
    if (!byItem[row.item_code]) byItem[row.item_code] = [];
    byItem[row.item_code].push(row);
  }

  for (const itemCode of Object.keys(byItem)) {
    const group = byItem[itemCode];
    const donors = group.filter((r) => r._surplus > 0).sort((a, b) => b._surplus - a._surplus);
    const receivers = group.filter((r) => r._deficit > 0).sort((a, b) => b._deficit - a._deficit);

    for (const rec of receivers) {
      for (const don of donors) {
        if (rec._deficit <= 0) break;
        if (don._surplus <= 0 || don.godown === rec.godown) continue;

        const moveQty = Number(Math.min(don._surplus, rec._deficit).toFixed(4));
        if (moveQty > 0) {
          don._surplus -= moveQty;
          rec._deficit -= moveQty;
          don.recommended_transfer_out = Number((don.recommended_transfer_out + moveQty).toFixed(4));
          rec.recommended_transfer_in = Number((rec.recommended_transfer_in + moveQty).toFixed(4));

          newTransfers.push({
            date: rec.date,
            item_code: rec.item_code,
            item_name: rec.item_name,
            unit: rec.unit,
            from_godown: don.godown,
            to_godown: rec.godown,
            transfer_qty: moveQty,
          });
        }
      }
    }

    for (const row of group) {
      if (row._deficit > 0) {
        row.recommended_order_qty = Number(row._deficit.toFixed(4));
        row.action = "ORDER";
      } else if (row.recommended_transfer_in > 0) {
        row.action = "TRANSFER_IN";
      } else if (row.recommended_transfer_out > 0) {
        row.action = "TRANSFER_OUT";
      } else if (row._surplus > 0) {
        row.recommended_hold_qty = Number(row._surplus.toFixed(4));
        row.action = "HOLD";
      } else {
        row.action = "OK";
      }
      delete row._surplus;
      delete row._deficit;
    }
  }

  return { updatedRows: updated, updatedTransfers: newTransfers };
}

export default function App() {
  const [orders, setOrders] = useState([]);
  const [transfers, setTransfers] = useState([]);
  const [sets, setSets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filters & UI toggles
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedGodown, setSelectedGodown] = useState("ALL");
  const [selectedAction, setSelectedAction] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState("planner");
  const [showUnitBreakdown, setShowUnitBreakdown] = useState(false);

  // Live Data Entry Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [txType, setTxType] = useState("RECEIPT"); // RECEIPT | ISSUE | TRANSFER
  const [txItemCode, setTxItemCode] = useState("");
  const [txGodown, setTxGodown] = useState("");
  const [txToGodown, setTxToGodown] = useState("");
  const [txQty, setTxQty] = useState("");
  const [recentLogs, setRecentLogs] = useState([]);
  const [toastMsg, setToastMsg] = useState("");

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        const data = await loadDashboardData();
        setOrders(data.orders);
        setTransfers(data.transfers);
        setSets(data.sets);

        const uniqueDates = [...new Set(data.orders.map((r) => r.date))].sort();
        if (uniqueDates.length > 0) {
          setSelectedDate(uniqueDates[uniqueDates.length - 1]);
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const dates = useMemo(
    () => [...new Set(orders.map((r) => r.date))].sort().reverse(),
    [orders]
  );
  const godowns = useMemo(
    () => ["ALL", ...[...new Set(orders.map((r) => r.godown))].sort()],
    [orders]
  );
  const godownList = useMemo(() => godowns.filter((g) => g !== "ALL"), [godowns]);

  const itemCatalog = useMemo(() => {
    const map = new Map();
    for (const r of orders) {
      if (!map.has(r.item_code)) {
        map.set(r.item_code, { code: r.item_code, name: r.item_name, unit: r.unit });
      }
    }
    return [...map.values()].sort((a, b) => a.code.localeCompare(b.code));
  }, [orders]);

  // Set default form values once catalog & godowns load
  useEffect(() => {
    if (itemCatalog.length > 0 && !txItemCode) setTxItemCode(itemCatalog[0].code);
    if (godownList.length > 0 && !txGodown) setTxGodown(godownList[0]);
    if (godownList.length > 1 && !txToGodown) setTxToGodown(godownList[1]);
  }, [itemCatalog, godownList, txItemCode, txGodown, txToGodown]);

  const selectedCatalogItem = useMemo(
    () => itemCatalog.find((i) => i.code === txItemCode),
    [itemCatalog, txItemCode]
  );

  // Handle New Inventory Entry & Live Recalculation
  function handleRecordTransaction(e) {
    e.preventDefault();
    const qtyNum = Number(txQty);
    if (!txItemCode || !txGodown || Number.isNaN(qtyNum) || qtyNum <= 0) return;
    if (txType === "TRANSFER" && (!txToGodown || txToGodown === txGodown)) return;

    const activeMonthRows = orders.filter((r) => r.date === selectedDate);
    const otherMonthRows = orders.filter((r) => r.date !== selectedDate);

    const modifiedMonthRows = activeMonthRows.map((row) => {
      if (row.item_code !== txItemCode) return row;

      if (txType === "RECEIPT" && row.godown === txGodown) {
        return { ...row, stock: Number((row.stock + qtyNum).toFixed(4)) };
      }
      if (txType === "ISSUE" && row.godown === txGodown) {
        return {
          ...row,
          stock: Math.max(0, Number((row.stock - qtyNum).toFixed(4))),
          rolling_monthly_consumption: Number(
            (row.rolling_monthly_consumption + qtyNum / 3).toFixed(4)
          ),
        };
      }
      if (txType === "TRANSFER") {
        if (row.godown === txGodown) {
          return { ...row, stock: Math.max(0, Number((row.stock - qtyNum).toFixed(4))) };
        }
        if (row.godown === txToGodown) {
          return { ...row, stock: Number((row.stock + qtyNum).toFixed(4)) };
        }
      }
      return row;
    });

    const { updatedRows, updatedTransfers } = recalculateMonthDecisions(modifiedMonthRows);

    setOrders([...otherMonthRows, ...updatedRows]);
    setTransfers((prev) => [
      ...prev.filter((t) => t.date !== selectedDate),
      ...updatedTransfers,
    ]);

    const unitLabel = selectedCatalogItem?.unit || "";
    const summaryText =
      txType === "RECEIPT"
        ? `Received +${qtyNum} ${unitLabel} of ${txItemCode} at ${txGodown}`
        : txType === "ISSUE"
        ? `Issued -${qtyNum} ${unitLabel} of ${txItemCode} from ${txGodown}`
        : `Transferred ${qtyNum} ${unitLabel} of ${txItemCode}: ${txGodown} → ${txToGodown}`;

    setRecentLogs((prev) => [
      { id: Date.now(), time: new Date().toLocaleTimeString(), text: summaryText, type: txType },
      ...prev.slice(0, 4),
    ]);
    setToastMsg(`${summaryText} — Planner recalculated`);
    setTimeout(() => setToastMsg(""), 4000);
    setTxQty("");
    setIsModalOpen(false);
  }

  const dateOrders = useMemo(
    () =>
      orders.filter(
        (r) =>
          (!selectedDate || r.date === selectedDate) &&
          (selectedGodown === "ALL" || r.godown === selectedGodown)
      ),
    [orders, selectedDate, selectedGodown]
  );

  const visibleOrders = useMemo(() => {
    const q = searchQuery.toLowerCase();
    return dateOrders.filter((r) => {
      const matchAction = selectedAction === "ALL" || r.action === selectedAction;
      const matchSearch =
        !q ||
        String(r.item_code).toLowerCase().includes(q) ||
        String(r.item_name).toLowerCase().includes(q) ||
        String(r.godown).toLowerCase().includes(q);
      return matchAction && matchSearch;
    });
  }, [dateOrders, selectedAction, searchQuery]);

  const visibleTransfers = useMemo(() => {
    const q = searchQuery.toLowerCase();
    return transfers.filter((r) => {
      const matchDate = !selectedDate || r.date === selectedDate;
      const matchGodown =
        selectedGodown === "ALL" ||
        r.from_godown === selectedGodown ||
        r.to_godown === selectedGodown;
      const matchSearch =
        !q ||
        String(r.item_code).toLowerCase().includes(q) ||
        String(r.item_name).toLowerCase().includes(q);
      return matchDate && matchGodown && matchSearch;
    });
  }, [transfers, selectedDate, selectedGodown, searchQuery]);

  const visibleSets = useMemo(
    () =>
      sets.filter(
        (r) =>
          (!selectedDate || r.date === selectedDate) &&
          (selectedGodown === "ALL" || r.godown === selectedGodown)
      ),
    [sets, selectedDate, selectedGodown]
  );

  const kpis = useMemo(() => {
    const orderRows = dateOrders.filter((r) => r.action === "ORDER");
    const holdRows = dateOrders.filter((r) => r.action === "HOLD");
    return {
      activeSkus: dateOrders.filter((r) => Number(r.stock) > 0).length,
      totalTracked: dateOrders.length,
      stockBreakdown: getUnitBreakdown(dateOrders, "stock"),
      orderCount: orderRows.length,
      orderBreakdown: getUnitBreakdown(orderRows, "recommended_order_qty"),
      transferCount: visibleTransfers.length,
      transferBreakdown: getUnitBreakdown(visibleTransfers, "transfer_qty"),
      holdCount: holdRows.length,
      holdBreakdown: getUnitBreakdown(holdRows, "recommended_hold_qty"),
    };
  }, [dateOrders, visibleTransfers]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0B0F19] text-slate-200 flex items-center justify-center gap-3">
        <RefreshCw className="w-5 h-5 animate-spin text-sky-400" />
        <span className="text-sm font-medium">Loading Krittim Inventory Engine...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#0B0F19] text-rose-300 flex items-center justify-center p-6">
        <div className="max-w-lg bg-[#111827] border border-rose-500/30 rounded-xl p-6 space-y-2">
          <h2 className="font-semibold text-base">Data Connection Error</h2>
          <p className="text-sm text-slate-400">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0B0F19] text-slate-100 font-sans">
      {/* Live Toast Confirmation */}
      {toastMsg && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-2.5 bg-emerald-950/95 border border-emerald-500/40 text-emerald-200 px-4 py-3 rounded-xl text-xs shadow-lg">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          <span>{toastMsg}</span>
        </div>
      )}

      {/* Top Bar */}
      <header className="border-b border-slate-800 bg-[#111827]/95 sticky top-0 z-20 backdrop-blur">
        <div className="max-w-7xl mx-auto px-6 py-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-white">
              Krittim<span className="text-sky-400">.sys</span>
            </h1>
            <p className="text-xs text-slate-400">
              Construction Inventory & Inter-Godown Allocation Engine
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2 bg-[#0B0F19] border border-slate-800 rounded-lg px-3 py-1.5">
              <Filter className="w-3.5 h-3.5 text-slate-400" />
              <span className="text-xs text-slate-400">Snapshot Month:</span>
              <select
                value={selectedDate}
                onChange={(e) => setSelectedDate(e.target.value)}
                className="bg-transparent text-xs font-medium text-white focus:outline-none"
              >
                {dates.map((d) => (
                  <option key={d} value={d} className="bg-[#111827]">
                    {d}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-2 bg-[#0B0F19] border border-slate-800 rounded-lg px-3 py-1.5">
              <span className="text-xs text-slate-400">Godown:</span>
              <select
                value={selectedGodown}
                onChange={(e) => setSelectedGodown(e.target.value)}
                className="bg-transparent text-xs font-medium text-white focus:outline-none"
              >
                {godowns.map((g) => (
                  <option key={g} value={g} className="bg-[#111827]">
                    {g}
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={() => setIsModalOpen(true)}
              className="flex items-center gap-1.5 bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs px-3.5 py-2 rounded-lg transition cursor-pointer"
            >
              <Plus className="w-4 h-4" />
              <span>Log Stock Entry</span>
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-5">
        {/* Clean KPI Strip */}
        <section className="space-y-2">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-[#111827] border border-slate-800 rounded-xl p-4">
              <div className="flex items-center justify-between text-slate-400 text-xs">
                <span>In-Stock Items</span>
                <Package className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="mt-2 text-2xl font-semibold text-white">
                {kpis.activeSkus}{" "}
                <span className="text-sm font-normal text-slate-400">
                  / {kpis.totalTracked} tracked
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                SKUs currently holding positive stock
              </p>
            </div>

            <div
              onClick={() => {
                setActiveTab("planner");
                setSelectedAction("ORDER");
              }}
              className="cursor-pointer bg-[#111827] border border-slate-800 hover:border-rose-500/40 rounded-xl p-4 transition"
            >
              <div className="flex items-center justify-between text-slate-400 text-xs">
                <span>Vendor Purchase Orders</span>
                <AlertTriangle className="w-4 h-4 text-rose-400" />
              </div>
              <div className="mt-2 text-2xl font-semibold text-rose-300">
                {kpis.orderCount} items
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Below target even after internal transfers
              </p>
            </div>

            <div
              onClick={() => setActiveTab("transfers")}
              className="cursor-pointer bg-[#111827] border border-slate-800 hover:border-sky-500/40 rounded-xl p-4 transition"
            >
              <div className="flex items-center justify-between text-slate-400 text-xs">
                <span>Inter-Godown Transfers</span>
                <ArrowLeftRight className="w-4 h-4 text-sky-400" />
              </div>
              <div className="mt-2 text-2xl font-semibold text-sky-300">
                {kpis.transferCount} routes
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Surplus-to-deficit warehouse rebalances
              </p>
            </div>

            <div
              onClick={() => {
                setActiveTab("planner");
                setSelectedAction("HOLD");
              }}
              className="cursor-pointer bg-[#111827] border border-slate-800 hover:border-purple-500/40 rounded-xl p-4 transition"
            >
              <div className="flex items-center justify-between text-slate-400 text-xs">
                <span>Overstock Hold Alerts</span>
                <PauseCircle className="w-4 h-4 text-purple-400" />
              </div>
              <div className="mt-2 text-2xl font-semibold text-purple-300">
                {kpis.holdCount} items
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Stock &gt; 1.5× lead-time target — freeze orders
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between">
            {recentLogs.length > 0 ? (
              <div className="text-xs text-sky-300">
                Latest live entry: <span className="font-mono">{recentLogs[0].text}</span> ({recentLogs[0].time})
              </div>
            ) : (
              <div />
            )}

            <button
              onClick={() => setShowUnitBreakdown((prev) => !prev)}
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition"
            >
              <span>{showUnitBreakdown ? "Hide" : "Show"} volume breakdown by unit (NOS, KM, KG...)</span>
              {showUnitBreakdown ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </button>
          </div>

          {showUnitBreakdown && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 bg-[#111827]/70 border border-slate-800 rounded-xl p-4 text-xs">
              <div>
                <div className="text-slate-400 font-medium mb-1.5">Total Stock by Unit</div>
                <div className="flex flex-wrap gap-1.5">
                  {kpis.stockBreakdown.map(([u, val]) => (
                    <span key={u} className="px-2 py-0.5 rounded bg-slate-800 font-mono text-slate-200">
                      {fmtQty(val, u)} {u}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-slate-400 font-medium mb-1.5">Order Volume by Unit</div>
                <div className="flex flex-wrap gap-1.5">
                  {kpis.orderBreakdown.length > 0 ? (
                    kpis.orderBreakdown.map(([u, val]) => (
                      <span key={u} className="px-2 py-0.5 rounded bg-rose-500/10 text-rose-300 font-mono">
                        {fmtQty(val, u)} {u}
                      </span>
                    ))
                  ) : (
                    <span className="text-slate-500">None</span>
                  )}
                </div>
              </div>
              <div>
                <div className="text-slate-400 font-medium mb-1.5">Transfer Volume by Unit</div>
                <div className="flex flex-wrap gap-1.5">
                  {kpis.transferBreakdown.length > 0 ? (
                    kpis.transferBreakdown.map(([u, val]) => (
                      <span key={u} className="px-2 py-0.5 rounded bg-sky-500/10 text-sky-300 font-mono">
                        {fmtQty(val, u)} {u}
                      </span>
                    ))
                  ) : (
                    <span className="text-slate-500">None</span>
                  )}
                </div>
              </div>
              <div>
                <div className="text-slate-400 font-medium mb-1.5">Excess Hold by Unit</div>
                <div className="flex flex-wrap gap-1.5">
                  {kpis.holdBreakdown.length > 0 ? (
                    kpis.holdBreakdown.map(([u, val]) => (
                      <span key={u} className="px-2 py-0.5 rounded bg-purple-500/10 text-purple-300 font-mono">
                        {fmtQty(val, u)} {u}
                      </span>
                    ))
                  ) : (
                    <span className="text-slate-500">None</span>
                  )}
                </div>
              </div>
            </div>
          )}
        </section>

        {/* Action Legend Strip */}
        {activeTab === "planner" && (
          <section className="bg-[#111827] border border-slate-800 rounded-xl px-4 py-3 flex flex-wrap items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2 text-slate-300 font-medium">
              <Info className="w-4 h-4 text-sky-400 shrink-0" />
              <span>Formula:</span>
              <span className="text-slate-400 font-normal">
                Target Stock = 3-Month Avg Usage × (Lead Time ÷ 30) × 1.15 buffer
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
              {Object.entries(ACTION_META).map(([key, meta]) => (
                <span key={key} className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${meta.dot}`} />
                  <strong className="text-slate-200">{key}:</strong> {meta.short}
                </span>
              ))}
            </div>
          </section>
        )}

        {/* Navigation Tabs & Search */}
        <section className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            {[
              { id: "planner", label: "Ordering Planner", count: visibleOrders.length },
              { id: "transfers", label: "Transfer Matrix", count: visibleTransfers.length },
              { id: "sets", label: "Material Sets", count: visibleSets.length },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-medium transition ${
                  activeTab === tab.id
                    ? "bg-sky-500/15 text-sky-300 border border-sky-500/30"
                    : "text-slate-400 hover:text-white hover:bg-slate-800/60"
                }`}
              >
                {tab.label}{" "}
                <span className="ml-1.5 text-[11px] opacity-75">({tab.count})</span>
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {activeTab === "planner" && (
              <div className="flex items-center gap-1 bg-[#111827] border border-slate-800 rounded-lg p-1">
                {["ALL", "ORDER", "TRANSFER_IN", "TRANSFER_OUT", "HOLD", "OK"].map((act) => (
                  <button
                    key={act}
                    onClick={() => setSelectedAction(act)}
                    className={`px-2 py-1 rounded text-[11px] font-medium transition ${
                      selectedAction === act
                        ? "bg-slate-700 text-white"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {act}
                  </button>
                ))}
              </div>
            )}

            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search item code or name..."
                className="bg-[#111827] border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500/50"
              />
            </div>
          </div>
        </section>

        {/* TAB 1: ORDERING PLANNER */}
        {activeTab === "planner" && (
          <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-400 bg-slate-900/50">
                    <th className="py-3 px-4">Item & Warehouse</th>
                    <th className="py-3 px-4 text-right">Current Stock</th>
                    <th className="py-3 px-4 text-right">
                      Required Target
                      <span className="block text-[9px] font-normal text-slate-500 normal-case">
                        (3M avg × lead time)
                      </span>
                    </th>
                    <th className="py-3 px-4">Recommended Decision</th>
                    <th className="py-3 px-4 text-right">Action Quantity</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70 text-xs">
                  {visibleOrders.map((row, idx) => {
                    const meta = ACTION_META[row.action] || ACTION_META.OK;
                    return (
                      <tr
                        key={`${row.godown}-${row.item_code}-${idx}`}
                        className="hover:bg-slate-800/30"
                      >
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-semibold text-white">
                              {row.item_code}
                            </span>
                            <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                              {row.godown}
                            </span>
                          </div>
                          <div className="text-[11px] text-slate-400 mt-0.5 max-w-md truncate">
                            {row.item_name}
                          </div>
                        </td>

                        <td className="py-3.5 px-4 text-right font-mono">
                          <span className="text-white font-medium">
                            {fmtQty(row.stock, row.unit)}
                          </span>{" "}
                          <span className="text-slate-500">{row.unit}</span>
                          <div className="text-[10px] text-slate-500">
                            Usage: {fmtQty(row.rolling_monthly_consumption, row.unit)}/mo
                          </div>
                        </td>

                        <td className="py-3.5 px-4 text-right font-mono">
                          <span className="text-slate-200">
                            {fmtQty(row.lead_time_target_stock, row.unit)}
                          </span>{" "}
                          <span className="text-slate-500">{row.unit}</span>
                          <div className="text-[10px] text-slate-500">
                            {row.lead_time_days}d vendor lead
                          </div>
                        </td>

                        <td className="py-3.5 px-4">
                          <span
                            className={`inline-block px-2.5 py-0.5 rounded border text-[11px] font-medium ${meta.badge}`}
                          >
                            {meta.label}
                          </span>
                          <div className="text-[11px] text-slate-400 mt-1">{meta.short}</div>
                        </td>

                        <td className="py-3.5 px-4 text-right font-mono font-semibold">
                          {row.recommended_order_qty > 0 && (
                            <span className="text-rose-300">
                              Order {fmtQty(row.recommended_order_qty, row.unit)} {row.unit}
                            </span>
                          )}
                          {row.recommended_transfer_in > 0 && (
                            <span className="text-sky-300">
                              Receive +{fmtQty(row.recommended_transfer_in, row.unit)} {row.unit}
                            </span>
                          )}
                          {row.recommended_transfer_out > 0 && (
                            <span className="text-amber-300">
                              Send -{fmtQty(row.recommended_transfer_out, row.unit)} {row.unit}
                            </span>
                          )}
                          {row.recommended_hold_qty > 0 && (
                            <span className="text-purple-300">
                              Hold {fmtQty(row.recommended_hold_qty, row.unit)} {row.unit}
                            </span>
                          )}
                          {row.action === "OK" && (
                            <span className="text-slate-500 font-normal">No action needed</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {visibleOrders.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-8 text-center text-slate-500">
                        No records match the current filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 2: INTER-GODOWN TRANSFERS */}
        {activeTab === "transfers" && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {visibleTransfers.map((tr, idx) => (
              <div
                key={`${tr.item_code}-${tr.from_godown}-${tr.to_godown}-${idx}`}
                className="bg-[#111827] border border-slate-800 rounded-xl p-4 space-y-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="font-mono text-xs font-semibold text-sky-300">
                      {tr.item_code}
                    </span>
                    <p className="text-xs text-slate-300 line-clamp-1">{tr.item_name}</p>
                  </div>
                  <span className="font-mono text-sm font-semibold text-white bg-slate-800 px-2.5 py-1 rounded-lg shrink-0">
                    {fmtQty(tr.transfer_qty, tr.unit)}{" "}
                    <span className="text-xs text-slate-400">{tr.unit}</span>
                  </span>
                </div>

                <div className="flex items-center justify-between text-xs bg-[#0B0F19] border border-slate-800/80 rounded-lg px-3 py-2">
                  <div>
                    <span className="block text-[10px] text-slate-500">FROM SURPLUS</span>
                    <span className="text-amber-300 font-medium">{tr.from_godown}</span>
                  </div>
                  <ArrowLeftRight className="w-3.5 h-3.5 text-slate-500 shrink-0 mx-2" />
                  <div className="text-right">
                    <span className="block text-[10px] text-slate-500">TO DEFICIT</span>
                    <span className="text-emerald-300 font-medium">{tr.to_godown}</span>
                  </div>
                </div>
              </div>
            ))}
            {visibleTransfers.length === 0 && (
              <div className="col-span-full bg-[#111827] border border-slate-800 rounded-xl p-8 text-center text-xs text-slate-500">
                No inter-godown transfers recommended for this selection.
              </div>
            )}
          </div>
        )}

        {/* TAB 3: MATERIAL SET AVAILABILITY */}
        {activeTab === "sets" && (
          <div className="bg-[#111827] border border-slate-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-slate-300">
                <Layers className="w-4 h-4 text-sky-400" />
                <span>
                  Complete Assembled Sets Available (Shared child MNB010174 proportionally allocated)
                </span>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-400 bg-slate-900/50">
                    <th className="py-3 px-4">Snapshot Month</th>
                    <th className="py-3 px-4">Godown</th>
                    <th className="py-3 px-4">Set Code</th>
                    <th className="py-3 px-4 text-right">Complete Sets Ready</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70 text-xs">
                  {visibleSets.map((s, idx) => (
                    <tr key={`${s.godown}-${s.set_code}-${idx}`} className="hover:bg-slate-800/30">
                      <td className="py-3 px-4 text-slate-400 font-mono">{s.date}</td>
                      <td className="py-3 px-4 text-slate-200">{s.godown}</td>
                      <td className="py-3 px-4 font-mono text-sky-300">Set {s.set_code}</td>
                      <td className="py-3 px-4 text-right font-mono font-semibold text-white">
                        {Math.floor(Number(s.available_sets) || 0).toLocaleString("en-IN")} SETS
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>

      {/* LIVE TRANSACTION ENTRY MODAL */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-[#111827] border border-slate-800 rounded-2xl max-w-md w-full p-6 space-y-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h2 className="text-base font-semibold text-white">Log Stock Movement</h2>
                <p className="text-xs text-slate-400">
                  Updates {selectedDate} stock & recalculates transfer/order recommendations live
                </p>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-slate-400 hover:text-white p-1"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleRecordTransaction} className="space-y-4 text-xs">
              {/* Transaction Type Selector */}
              <div className="grid grid-cols-3 gap-2 bg-[#0B0F19] p-1 rounded-xl border border-slate-800">
                {[
                  { id: "RECEIPT", label: "+ Vendor Receipt" },
                  { id: "ISSUE", label: "- Site Issue" },
                  { id: "TRANSFER", label: "⇄ Transfer" },
                ].map((opt) => (
                  <button
                    type="button"
                    key={opt.id}
                    onClick={() => setTxType(opt.id)}
                    className={`py-2 rounded-lg font-medium transition ${
                      txType === opt.id
                        ? "bg-sky-500 text-slate-950 font-semibold"
                        : "text-slate-400 hover:text-white"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              {/* Item Selector */}
              <div className="space-y-1.5">
                <label className="text-slate-300 font-medium block">Material SKU</label>
                <select
                  value={txItemCode}
                  onChange={(e) => setTxItemCode(e.target.value)}
                  className="w-full bg-[#0B0F19] border border-slate-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-sky-500"
                >
                  {itemCatalog.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.code} — {item.name} ({item.unit})
                    </option>
                  ))}
                </select>
              </div>

              {/* Source / Target Godown */}
              <div className={txType === "TRANSFER" ? "grid grid-cols-2 gap-3" : "space-y-1.5"}>
                <div className="space-y-1.5">
                  <label className="text-slate-300 font-medium block">
                    {txType === "TRANSFER" ? "From Godown" : "Godown"}
                  </label>
                  <select
                    value={txGodown}
                    onChange={(e) => setTxGodown(e.target.value)}
                    className="w-full bg-[#0B0F19] border border-slate-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-sky-500"
                  >
                    {godownList.map((g) => (
                      <option key={g} value={g}>
                        {g}
                      </option>
                    ))}
                  </select>
                </div>

                {txType === "TRANSFER" && (
                  <div className="space-y-1.5">
                    <label className="text-slate-300 font-medium block">To Godown</label>
                    <select
                      value={txToGodown}
                      onChange={(e) => setTxToGodown(e.target.value)}
                      className="w-full bg-[#0B0F19] border border-slate-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-sky-500"
                    >
                      {godownList
                        .filter((g) => g !== txGodown)
                        .map((g) => (
                          <option key={g} value={g}>
                            {g}
                          </option>
                        ))}
                    </select>
                  </div>
                )}
              </div>

              {/* Quantity Input */}
              <div className="space-y-1.5">
                <label className="text-slate-300 font-medium block">
                  Quantity ({selectedCatalogItem?.unit || "Units"})
                </label>
                <input
                  type="number"
                  step="any"
                  min="0.01"
                  required
                  value={txQty}
                  onChange={(e) => setTxQty(e.target.value)}
                  placeholder={`Enter quantity in ${selectedCatalogItem?.unit || "units"}...`}
                  className="w-full bg-[#0B0F19] border border-slate-800 rounded-lg px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 font-mono"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-3.5 py-2 rounded-lg text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold transition cursor-pointer"
                >
                  Apply & Recalculate
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}