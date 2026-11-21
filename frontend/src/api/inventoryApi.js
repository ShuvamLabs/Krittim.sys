const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
const apiBaseUrl =
  configuredApiBaseUrl?.replace(/\/+$/, "") ||
  (import.meta.env.DEV ? "http://localhost:8000" : "");

function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((header) => header.trim());
  return lines.slice(1).map((line) => {
    const values = [];
    let value = "";
    let inQuotes = false;
    for (const character of line) {
      if (character === '"') {
        inQuotes = !inQuotes;
      } else if (character === "," && !inQuotes) {
        values.push(value.trim());
        value = "";
      } else {
        value += character;
      }
    }
    values.push(value.trim());
    return Object.fromEntries(
      headers.map((header, index) => {
        const fieldValue = values[index] ?? "";
        const number = Number(fieldValue);
        return [
          header,
          fieldValue !== "" &&
          !Number.isNaN(number) &&
          !["date", "item_code", "set_code"].includes(header)
            ? number
            : fieldValue,
        ];
      })
    );
  });
}

async function loadCsv(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Could not load ${path} (HTTP ${response.status}).`);
  }
  return parseCSV(await response.text());
}

function numberOrZero(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

async function fetchWithTimeout(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    return await fetch(url, { signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

function normalizeRecommendation(row, decisionDate, catalog) {
  const catalogItem = catalog.get(row.item_code) || {};
  const transferIn = numberOrZero(row.recommended_transfer_in);
  const transferOut = numberOrZero(row.recommended_transfer_out);
  let action = String(row.action || "OK").toUpperCase();
  if (action === "TRANSFER") {
    action =
      transferIn > 0
        ? "TRANSFER_IN"
        : transferOut > 0
          ? "TRANSFER_OUT"
          : "OK";
  } else if (action === "REDUCE") {
    action = "HOLD";
  }

  return {
    date: row.decision_date || decisionDate,
    godown: row.godown || row.godown_name || "",
    item_code: row.item_code,
    item_name: row.item_name || catalogItem.item_name || "",
    unit: row.unit || catalogItem.unit || "",
    role: row.role || catalogItem.role || "",
    lead_time_days: numberOrZero(row.lead_time_days),
    stock: numberOrZero(
      row.stock ?? row.current_stock ?? row.effective_godown_stock
    ),
    qty_consumed: numberOrZero(row.qty_consumed),
    rolling_monthly_consumption: numberOrZero(
      row.rolling_monthly_consumption ?? row.recent_monthly_consumption
    ),
    lead_time_target_stock: numberOrZero(
      row.target ?? row.lead_time_target_stock
    ),
    action,
    recommended_order_qty: numberOrZero(row.recommended_order_qty),
    recommended_transfer_in: transferIn,
    recommended_transfer_out: transferOut,
    recommended_hold_qty: numberOrZero(row.recommended_hold_qty),
  };
}

function recommendationsToTransfers(rows) {
  const transfers = [];
  const byItem = new Map();
  for (const row of rows) {
    if (!byItem.has(row.item_code)) byItem.set(row.item_code, []);
    byItem.get(row.item_code).push(row);
  }

  for (const itemRows of byItem.values()) {
    const donors = itemRows
      .filter((row) => row.recommended_transfer_out > 0)
      .map((row) => ({ ...row, remaining: row.recommended_transfer_out }));
    const receivers = itemRows
      .filter((row) => row.recommended_transfer_in > 0)
      .map((row) => ({ ...row, remaining: row.recommended_transfer_in }));

    for (const receiver of receivers) {
      for (const donor of donors) {
        if (receiver.remaining <= 0) break;
        if (donor.remaining <= 0 || donor.godown === receiver.godown) continue;
        const quantity = Math.min(donor.remaining, receiver.remaining);
        donor.remaining -= quantity;
        receiver.remaining -= quantity;
        transfers.push({
          date: receiver.date,
          item_code: receiver.item_code,
          item_name: receiver.item_name,
          unit: receiver.unit,
          from_godown: donor.godown,
          to_godown: receiver.godown,
          transfer_qty: quantity,
        });
      }
    }
  }
  return transfers;
}

async function loadLiveRecommendations(decisionDate, catalog) {
  if (!apiBaseUrl) return null;

  const healthResponse = await fetchWithTimeout(`${apiBaseUrl}/health`);
  if (!healthResponse.ok) {
    throw new Error(`Backend health check failed (HTTP ${healthResponse.status}).`);
  }

  const url = new URL(`${apiBaseUrl}/planning/recommendations`);
  url.searchParams.set("decision_date", decisionDate);
  const recommendationsResponse = await fetchWithTimeout(url);
  if (!recommendationsResponse.ok) {
    throw new Error(
      `Planning recommendations failed (HTTP ${recommendationsResponse.status}).`
    );
  }
  const recommendations = await recommendationsResponse.json();
  if (!Array.isArray(recommendations)) {
    throw new Error("Backend returned an invalid recommendations response.");
  }
  return recommendations.map((row) =>
    normalizeRecommendation(row, decisionDate, catalog)
  );
}

export async function loadDashboardData() {
  const [csvOrders, csvTransfers, sets] = await Promise.all([
    loadCsv("/backend_ready/ordering_recommendations.csv"),
    loadCsv("/backend_ready/transfer_recommendations.csv"),
    loadCsv("/backend_ready/material_set_availability.csv"),
  ]);
  const catalog = new Map();
  for (const row of csvOrders) {
    if (!catalog.has(row.item_code)) catalog.set(row.item_code, row);
  }
  const dates = csvOrders.map((row) => row.date).filter(Boolean).sort();
  const decisionDate = dates[dates.length - 1];
  if (!decisionDate) {
    throw new Error("No decision dates were found in the fallback recommendations.");
  }

  try {
    const liveOrders = await loadLiveRecommendations(decisionDate, catalog);
    if (!liveOrders?.length) {
      throw new Error("Backend returned no recommendations.");
    }
    const liveTransfers = recommendationsToTransfers(liveOrders);
    return {
      orders: [
        ...csvOrders.filter((row) => row.date !== decisionDate),
        ...liveOrders,
      ],
      transfers: [
        ...csvTransfers.filter((row) => row.date !== decisionDate),
        ...liveTransfers,
      ],
      sets,
    };
  } catch (error) {
    console.warn("Using bundled CSV data because the backend is unavailable:", error);
    return { orders: csvOrders, transfers: csvTransfers, sets };
  }
}
