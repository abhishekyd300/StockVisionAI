/* ============================================================
   StockVision AI — Main JavaScript
   ============================================================ */

'use strict';

// ── State ──────────────────────────────────────────────────
let mainChart = null;
let acTimeout = null;

// ── DOM References ─────────────────────────────────────────
const input  = document.getElementById('company-input');
const acList = document.getElementById('autocomplete-list');

// ══════════════════════════════════════════════════════════
//  AUTOCOMPLETE
// ══════════════════════════════════════════════════════════

input.addEventListener('input', () => {
  clearTimeout(acTimeout);
  const q = input.value.trim();
  if (q.length < 2) { acList.style.display = 'none'; return; }
  acTimeout = setTimeout(() => fetchAC(q), 280);
});

input.addEventListener('keydown', e => {
  if (e.key === 'Enter')  { acList.style.display = 'none'; runPrediction(); }
  if (e.key === 'Escape') { acList.style.display = 'none'; }
});

document.addEventListener('click', e => {
  if (!e.target.closest('.search-wrapper')) acList.style.display = 'none';
});

/**
 * Fetch autocomplete suggestions from the backend search API.
 * @param {string} q - Search query
 */
async function fetchAC(q) {
  try {
    const res  = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    renderAC(data);
  } catch {
    acList.style.display = 'none';
  }
}

/**
 * Render autocomplete dropdown items.
 * @param {Array} items - List of {symbol, name, type} objects
 */
function renderAC(items) {
  if (!items.length) { acList.style.display = 'none'; return; }
  acList.innerHTML = items.map(i => `
    <div class="ac-item" onclick="selectAC('${i.symbol}','${escHtml(i.name)}')">
      <span class="ac-symbol">${escHtml(i.symbol)}</span>
      <span class="ac-name">${escHtml(i.name)}</span>
      <span class="ac-type">${escHtml(i.type || '')}</span>
    </div>
  `).join('');
  acList.style.display = 'block';
}

/**
 * Called when user clicks an autocomplete suggestion.
 * @param {string} symbol - Ticker symbol
 */
function selectAC(symbol) {
  input.value = symbol;
  acList.style.display = 'none';
  runPrediction();
}

/**
 * Called when a quick-chip button is clicked.
 * @param {string} ticker - Pre-defined ticker symbol
 */
function quickSearch(ticker) {
  input.value = ticker;
  runPrediction();
}

// ══════════════════════════════════════════════════════════
//  PREDICTION — API CALL
// ══════════════════════════════════════════════════════════

/**
 * Main prediction flow: validate input → call API → render dashboard.
 */
async function runPrediction() {
  const company = input.value.trim();
  if (!company) return;

  acList.style.display = 'none';
  setError('');
  setLoading(true);
  document.getElementById('dashboard').style.display = 'none';

  try {
    const res  = await fetch('/api/predict', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ company }),
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      setError(data.error || 'Failed to fetch prediction.');
      setLoading(false);
      return;
    }

    renderDashboard(data);
  } catch {
    setError('Network error. Is the server running?');
  }

  setLoading(false);
}

// ══════════════════════════════════════════════════════════
//  DASHBOARD RENDERER
// ══════════════════════════════════════════════════════════

/**
 * Populate all dashboard elements with API response data.
 * @param {Object} d - Full API response object
 */
function renderDashboard(d) {
  // Currency symbol
  const sym = d.currency === 'INR' ? '₹'
            : d.currency === 'GBP' ? '£'
            : d.currency === 'EUR' ? '€'
            : '$';

  // Formatters
  const fmt = (v, dec = 2) =>
    v != null
      ? sym + Number(v).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })
      : '—';

  const fmtBig = v => {
    if (!v)        return '—';
    if (v >= 1e12) return sym + (v / 1e12).toFixed(2) + 'T';
    if (v >= 1e9)  return sym + (v / 1e9).toFixed(2)  + 'B';
    if (v >= 1e6)  return sym + (v / 1e6).toFixed(2)  + 'M';
    return sym + Number(v).toLocaleString();
  };

  const fmtVol = v => {
    if (!v)        return '—';
    if (v >= 1e9)  return (v / 1e9).toFixed(2)  + 'B';
    if (v >= 1e6)  return (v / 1e6).toFixed(2)  + 'M';
    if (v >= 1e3)  return (v / 1e3).toFixed(1)  + 'K';
    return String(v);
  };

  // ── Company Header ──
  document.getElementById('d-company-name').textContent = d.company_name;
  document.getElementById('d-ticker').textContent       = d.ticker;
  document.getElementById('d-sector').textContent       = d.info?.sector   || 'N/A';
  document.getElementById('d-country').textContent      = d.info?.country  || 'N/A';
  document.getElementById('d-currency').textContent     = d.currency;
  document.getElementById('d-price').textContent        = fmt(d.current_price);

  const chgBadge = document.getElementById('d-change-badge');
  const isUp     = d.price_change_pct >= 0;
  chgBadge.textContent = `${isUp ? '▲' : '▼'} ${Math.abs(d.price_change_pct).toFixed(2)}% (${isUp ? '+' : ''}${fmt(d.price_change)})`;
  chgBadge.className   = 'price-change-badge ' + (isUp ? 'positive' : 'negative');

  // ── KPI Cards ──
  document.getElementById('k-current').textContent  = fmt(d.current_price);
  document.getElementById('k-pred-end').textContent = fmt(d.pred_end);

  const predUp = d.pred_change_pct >= 0;
  document.getElementById('k-pred-pct').textContent  = `${predUp ? '▲ +' : '▼ '}${d.pred_change_pct.toFixed(2)}% in 14 days`;
  document.getElementById('k-pred-high').textContent = fmt(d.pred_high);
  document.getElementById('k-pred-low').textContent  = fmt(d.pred_low);

  // ── Market Stats ──
  document.getElementById('s-52h').textContent      = fmt(d.info?.['52w_high']);
  document.getElementById('s-52l').textContent      = fmt(d.info?.['52w_low']);
  document.getElementById('s-mcap').textContent     = fmtBig(d.info?.market_cap);
  document.getElementById('s-pe').textContent       = d.info?.pe_ratio ? Number(d.info.pe_ratio).toFixed(2) : '—';
  document.getElementById('s-vol').textContent      = fmtVol(d.info?.avg_volume);
  document.getElementById('s-industry').textContent = d.info?.industry || '—';

  // ── Chart & Table ──
  buildChart(d, sym);
  buildTable(d.prediction, d.current_price, fmt);

  document.getElementById('dashboard').style.display = 'block';
}

// ══════════════════════════════════════════════════════════
//  CHART BUILDER
// ══════════════════════════════════════════════════════════

/**
 * Build (or rebuild) the main Chart.js line chart.
 * @param {Object} d   - Full API response
 * @param {string} sym - Currency symbol (e.g. '$', '₹')
 */
function buildChart(d, sym) {
  if (mainChart) { mainChart.destroy(); mainChart = null; }

  const hist  = d.historical;
  const pred  = d.prediction;

  // Labels & data arrays
  const histLabels = hist.map(h => h.ds.slice(0, 10));
  const histPrices = hist.map(h => +h.y.toFixed(2));

  const predLabels = pred.map(p => p.ds.slice(0, 10));
  const predYhat   = pred.map(p => +p.yhat.toFixed(2));
  const predLow    = pred.map(p => +p.yhat_lower.toFixed(2));
  const predHigh   = pred.map(p => +p.yhat_upper.toFixed(2));

  // Bridge last historical point into the forecast for a seamless line
  const joinPrice = histPrices[histPrices.length - 1];

  const allLabels  = [...histLabels, ...predLabels];
  const histDataset = [...histPrices, ...Array(predLabels.length).fill(null)];
  const predDataset = [...Array(histLabels.length - 1).fill(null), joinPrice, ...predYhat];
  const bandLow     = [...Array(histLabels.length - 1).fill(null), joinPrice, ...predLow];
  const bandHigh    = [...Array(histLabels.length - 1).fill(null), joinPrice, ...predHigh];

  const ctx = document.getElementById('main-chart').getContext('2d');

  // Gradient fills
  const gradBlue   = ctx.createLinearGradient(0, 0, 0, 380);
  gradBlue.addColorStop(0, 'rgba(79,124,255,0.25)');
  gradBlue.addColorStop(1, 'rgba(79,124,255,0)');

  const gradPurple = ctx.createLinearGradient(0, 0, 0, 380);
  gradPurple.addColorStop(0, 'rgba(162,89,255,0.28)');
  gradPurple.addColorStop(1, 'rgba(162,89,255,0)');

  mainChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: allLabels,
      datasets: [
        // Confidence band HIGH (fills down to CI Low via fill: '+1')
        {
          label: 'CI High',
          data: bandHigh,
          borderColor: 'transparent',
          backgroundColor: 'rgba(162,89,255,0.15)',
          fill: '+1',
          pointRadius: 0,
          tension: 0.4,
          order: 4,
        },
        // Confidence band LOW
        {
          label: 'CI Low',
          data: bandLow,
          borderColor: 'transparent',
          backgroundColor: 'rgba(162,89,255,0.15)',
          fill: false,
          pointRadius: 0,
          tension: 0.4,
          order: 5,
        },
        // Actual historical price line
        {
          label: 'Actual Price',
          data: histDataset,
          borderColor: '#4f7cff',
          backgroundColor: gradBlue,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 2.5,
          tension: 0.35,
          order: 1,
        },
        // AI Forecast price line
        {
          label: 'AI Forecast',
          data: predDataset,
          borderColor: '#a259ff',
          backgroundColor: gradPurple,
          fill: true,
          pointRadius: 0,
          pointHoverRadius: 5,
          borderWidth: 2.5,
          tension: 0.4,
          order: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(13,22,40,0.95)',
          borderColor: 'rgba(99,120,200,0.3)',
          borderWidth: 1,
          titleColor: '#9db4ff',
          bodyColor: '#e8eaf6',
          padding: 12,
          callbacks: {
            label: ctx => {
              if (ctx.dataset.label === 'CI High') return `  Upper CI: ${sym}${ctx.parsed.y?.toFixed(2) ?? ''}`;
              if (ctx.dataset.label === 'CI Low')  return `  Lower CI: ${sym}${ctx.parsed.y?.toFixed(2) ?? ''}`;
              if (ctx.raw === null) return null;
              return `  ${ctx.dataset.label}: ${sym}${ctx.parsed.y?.toFixed(2)}`;
            },
          },
        },
        // Vertical "Today" divider line
        annotation: {
          annotations: {
            dividerLine: {
              type: 'line',
              xMin: histLabels.length - 1,
              xMax: histLabels.length - 1,
              borderColor: 'rgba(255,255,255,0.2)',
              borderWidth: 1.5,
              borderDash: [6, 4],
              label: {
                display: true,
                content: 'Today',
                position: 'start',
                color: 'rgba(255,255,255,0.5)',
                font: { size: 11, family: 'Inter' },
                yAdjust: -8,
              },
            },
          },
        },
      },
      scales: {
        x: {
          grid:   { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks:  { color: '#7a8ab5', font: { size: 11 }, maxTicksLimit: 10, maxRotation: 0 },
          border: { display: false },
        },
        y: {
          grid:     { color: 'rgba(255,255,255,0.04)', drawTicks: false },
          ticks:    { color: '#7a8ab5', font: { size: 11 }, callback: v => sym + v.toLocaleString() },
          border:   { display: false },
          position: 'right',
        },
      },
    },
  });
}

// ══════════════════════════════════════════════════════════
//  FORECAST TABLE
// ══════════════════════════════════════════════════════════

/**
 * Build the 14-day forecast table.
 * @param {Array}    prediction    - Array of {ds, yhat, yhat_lower, yhat_upper}
 * @param {number}   currentPrice  - Current stock price
 * @param {Function} fmt           - Currency formatter
 */
function buildTable(prediction, currentPrice, fmt) {
  const tbody = document.getElementById('forecast-tbody');
  tbody.innerHTML = prediction.map((p, i) => {
    const chg  = (p.yhat - currentPrice) / currentPrice * 100;
    const isUp = chg >= 0;
    const date = new Date(p.ds).toLocaleDateString('en-US', {
      weekday: 'short', month: 'short', day: 'numeric',
    });
    return `<tr>
      <td>${i + 1}</td>
      <td class="td-date">${date}</td>
      <td class="td-pred">${fmt(p.yhat)}</td>
      <td>${fmt(p.yhat_lower)}</td>
      <td>${fmt(p.yhat_upper)}</td>
      <td class="td-change ${isUp ? 'up' : 'down'}">${isUp ? '▲ +' : '▼ '}${Math.abs(chg).toFixed(2)}%</td>
    </tr>`;
  }).join('');
}

// ══════════════════════════════════════════════════════════
//  UTILITY HELPERS
// ══════════════════════════════════════════════════════════

/**
 * Toggle loading spinner and disable the predict button.
 * @param {boolean} show
 */
function setLoading(show) {
  document.getElementById('spinner').style.display    = show ? 'flex' : 'none';
  document.getElementById('predict-btn').disabled     = show;
}

/**
 * Show or hide the error message banner.
 * @param {string} msg - Error text (empty string to hide)
 */
function setError(msg) {
  const el = document.getElementById('error-msg');
  if (msg) {
    el.textContent    = '⚠️ ' + msg;
    el.style.display  = 'block';
  } else {
    el.style.display  = 'none';
  }
}

/**
 * Escape HTML special characters to prevent XSS in innerHTML.
 * @param {string} s - Raw string
 * @returns {string} - Escaped string
 */
function escHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
