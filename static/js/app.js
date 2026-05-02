/* ============================================================
   Portfolio Dashboard – JavaScript
   Integrates with Flask API and Jinja2 templates
   ============================================================ */

// ---------------------------------------------------------------------------
// API Layer
// ---------------------------------------------------------------------------
const API = {
    getMarketData:  () => fetch('/api/market-data').then(r => r.json()),
    getPortfolio:   () => fetch('/api/portfolio').then(r => r.json()),
    getSummary:     () => fetch('/api/summary').then(r => r.json()),
    updateHolding:  (d) => fetch('/api/portfolio/holding',  { method:'PUT',    headers:{'Content-Type':'application/json'}, body:JSON.stringify(d) }).then(r=>r.json()),
    addHolding:     (d) => fetch('/api/portfolio/holding',  { method:'POST',   headers:{'Content-Type':'application/json'}, body:JSON.stringify(d) }).then(r=>r.json()),
    deleteHolding:  (d) => fetch('/api/portfolio/holding',  { method:'DELETE', headers:{'Content-Type':'application/json'}, body:JSON.stringify(d) }).then(r=>r.json()),
    updateOption:   (d) => fetch('/api/portfolio/option',   { method:'PUT',    headers:{'Content-Type':'application/json'}, body:JSON.stringify(d) }).then(r=>r.json()),
    addOption:      (d) => fetch('/api/portfolio/option',   { method:'POST',   headers:{'Content-Type':'application/json'}, body:JSON.stringify(d) }).then(r=>r.json()),
    deleteOption:   (d) => fetch('/api/portfolio/option',   { method:'DELETE', headers:{'Content-Type':'application/json'}, body:JSON.stringify(d) }).then(r=>r.json()),
    updateSettings: (d) => fetch('/api/portfolio/settings', { method:'PUT',    headers:{'Content-Type':'application/json'}, body:JSON.stringify(d) }).then(r=>r.json()),
    recordTrade:    (d) => fetch('/api/portfolio/trade',    { method:'POST',   headers:{'Content-Type':'application/json'}, body:JSON.stringify(d) }).then(r=>r.json()),
    deleteTrade:    (d) => fetch('/api/portfolio/trade',    { method:'DELETE', headers:{'Content-Type':'application/json'}, body:JSON.stringify(d) }).then(r=>r.json()),
    clearCache:     () => fetch('/api/cache/clear', { method:'POST' }).then(r=>r.json()),
};

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

function showLoading() { const el=$('#loading'); if(el) el.style.display='flex'; }
function hideLoading() { const el=$('#loading'); if(el) el.style.display='none'; }

function fmt$(n)   { return n!=null&&!isNaN(n) ? '$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}) : '—'; }
function fmtInt$(n) { return n!=null&&!isNaN(n) ? '$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0}) : '—'; }
function fmtPct(n) { return n!=null&&!isNaN(n) ? (n>=0?'+':'')+Number(n).toFixed(2)+'%' : '—'; }
function clsPct(n) { return n>0?'positive':n<0?'negative':'neutral'; }

function signalBadge(sig) {
    if (!sig||!sig.action) return '<span class="badge badge-hold">HOLD</span>';
    const m = {STR:'badge-str',BTD:'badge-btd',WATCH:'badge-watch',HOLD:'badge-hold'};
    return `<span class="badge ${m[sig.action]||'badge-hold'}">${sig.action}</span>`;
}
function signalRowCls(sig) {
    if (!sig||!sig.action) return '';
    return {STR:'signal-str',BTD:'signal-btd',WATCH:'signal-watch',HOLD:''}[sig.action]||'';
}

function showToast(msg, type='success') {
    let c = $('.toast-container');
    if (!c) { c=document.createElement('div'); c.className='toast-container'; document.body.appendChild(c); }
    const t = document.createElement('div');
    t.className = `toast toast-${type}`;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(()=>{ t.style.opacity='0'; t.style.transition='opacity .3s'; setTimeout(()=>t.remove(),300); }, 3000);
}

// ---------------------------------------------------------------------------
// ========================  DASHBOARD PAGE  ================================
// ---------------------------------------------------------------------------

// On page load: use cached data (no cache clear). Refresh button clears cache.
async function loadDashboard() {
    const table = $('#market-table');
    if (!table) return;
    showLoading();
    try {
        const [mkt, pf] = await Promise.all([API.getMarketData(), API.getPortfolio()]);
        renderDashboard(mkt, pf);
    } catch(e) { console.error(e); showToast('Failed to load market data','error'); }
    finally { hideLoading(); }
}

async function refreshMarketData() {
    const table = $('#market-table');
    if (!table) return;
    showLoading();
    try {
        await API.clearCache();
        const [mkt, pf] = await Promise.all([API.getMarketData(), API.getPortfolio()]);
        renderDashboard(mkt, pf);
        showToast('Market data refreshed');
    } catch(e) { console.error(e); showToast('Failed to load market data','error'); }
    finally { hideLoading(); }
}

function renderDashboard(mkt, pf) {
    const bucketMap = {};
    const holdingMap = {};  // ticker -> {actual_shares, avg_price}
    const bucketNames = { tech_stocks:'Tech Stocks', growth_etfs:'Growth ETFs', defensive_etfs:'Defensive ETFs', gold_silver:'Gold & Silver', hedges:'Hedges' };
    for (const [bk, bd] of Object.entries(pf.buckets||{})) {
        for (const h of bd.holdings||[]) {
            bucketMap[h.ticker] = bk;
            holdingMap[h.ticker] = h;
        }
    }
    for (const o of pf.options||[]) { if(o.underlying) bucketMap[o.underlying]='hedges'; }

    const data = mkt.data || {};
    const tbody = $('#market-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const strSignals=[], btdSignals=[];
    const bucketOrder = ['tech_stocks','growth_etfs','defensive_etfs','gold_silver','hedges'];
    const sorted = Object.keys(data).sort((a,b)=>{
        const ba=bucketOrder.indexOf(bucketMap[a]||''), bb=bucketOrder.indexOf(bucketMap[b]||'');
        if(ba!==bb) return ba-bb;
        return a.localeCompare(b);
    });

    for (const ticker of sorted) {
        const d = data[ticker];
        if (d.error) continue;
        const bucket = bucketMap[ticker]||'';
        const sig = d.signal||{};
        const h = holdingMap[ticker];
        const shares = parseFloat(h?.actual_shares)||0;
        const avg    = parseFloat(h?.avg_price)||0;
        const value  = shares * (d.price||0);
        const cost   = shares * avg;
        const pnl    = shares>0 ? value - cost : null;
        const pnlPct = cost>0&&pnl!=null ? (pnl/cost)*100 : null;

        const tr = document.createElement('tr');
        tr.className = signalRowCls(sig);
        tr.dataset.bucket = bucket;
        tr.dataset.signal = (sig.action||'hold').toLowerCase();
        tr.innerHTML = `
            <td class="text-sm">${bucketNames[bucket]||bucket}</td>
            <td><strong><a href="/history?ticker=${ticker}" class="ticker-link">${ticker}</a></strong></td>
            <td class="num">${fmt$(d.price)}</td>
            <td class="num">${shares||'—'}</td>
            <td class="num">${avg?fmt$(avg):'—'}</td>
            <td class="num">${value?fmt$(value):'—'}</td>
            <td class="num"><span class="${clsPct(pnl)}">${pnl!=null?fmt$(pnl):'—'}</span></td>
            <td class="num"><span class="${clsPct(pnlPct)}">${pnlPct!=null?fmtPct(pnlPct):'—'}</span></td>
            <td class="num"><span class="${clsPct(d.div_sma)}">${fmtPct(d.div_sma)}</span></td>
            <td class="num"><span class="${clsPct(d.div_ema)}">${fmtPct(d.div_ema)}</span></td>
            <td class="num"><span class="${clsPct(d.chg_1m)}">${fmtPct(d.chg_1m)}</span></td>
            <td>${signalBadge(sig)}</td>
            <td class="text-sm">${sig.label||''}</td>
        `;
        tbody.appendChild(tr);
        if (sig.action==='STR') strSignals.push({ticker, label:sig.label, div:d.div_sma});
        if (sig.action==='BTD') btdSignals.push({ticker, label:sig.label, div:d.div_sma});
    }

    const strEl = $('#str-signals .signal-list');
    if (strEl) {
        strEl.innerHTML = strSignals.length===0
            ? '<li class="text-muted">No STR signals</li>'
            : strSignals.map(s=>`<li><span class="badge badge-str">${s.ticker}</span> ${s.label} (${fmtPct(s.div)})</li>`).join('');
    }
    const btdEl = $('#btd-signals .signal-list');
    if (btdEl) {
        btdEl.innerHTML = btdSignals.length===0
            ? '<li class="text-muted">No BTD signals</li>'
            : btdSignals.map(s=>`<li><span class="badge badge-btd">${s.ticker}</span> ${s.label} (${fmtPct(s.div)})</li>`).join('');
    }
    const ts = $('#last-updated-time');
    if (ts) ts.textContent = new Date().toLocaleString();
}

function filterTable(value, btn) {
    $$('.filter-btn').forEach(b=>b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    $$('#market-table tbody tr').forEach(row => {
        row.style.display = (value==='all' || row.dataset.bucket===value) ? '' : 'none';
    });
}

// ---------------------------------------------------------------------------
// ========================  PORTFOLIO PAGE  ================================
// ---------------------------------------------------------------------------

let _pfData = null;
let _priceMap = {};

/**
 * Progressive load: render portfolio data immediately from local JSON,
 * then fetch market prices in background and patch cells as they arrive.
 */
async function loadPortfolioData() {
    // Step 1: fetch portfolio JSON (fast, local) and render immediately
    try {
        _pfData = await API.getPortfolio();
        renderPortfolioSettings(_pfData);
        renderAllBuckets(_pfData);          // renders with _priceMap (may be empty on first load)
        renderOptionsTable(_pfData.options||[]);
    } catch(e) { console.error(e); showToast('Failed to load portfolio','error'); return; }

    // Step 2: fetch market data in background (uses 10-min cache, no blocking)
    API.getMarketData().then(mkt => {
        _priceMap = {};
        for (const [tk, d] of Object.entries(mkt.data||{})) {
            if (d.price!=null) _priceMap[tk] = d.price;
        }
        // Patch live prices into already-rendered rows
        patchLivePrices();
    }).catch(e => console.warn('Market data fetch failed, portfolio shown without live prices:', e));
}

/** Update value/P&L cells in-place once market prices arrive. */
function patchLivePrices() {
    $$('.bucket-section').forEach(section => {
        const bk = section.dataset.bucket;
        const holdings = _pfData?.buckets?.[bk]?.holdings||[];
        let actualTotal = 0;
        const ta = _pfData?.buckets?.[bk]?.target_amount||0;

        section.querySelectorAll('.holdings-table tbody tr').forEach(row => {
            const ticker = row.dataset.ticker;
            const h = holdings.find(x=>x.ticker===ticker);
            if (!h) return;
            const shares = parseFloat(h.actual_shares)||0;
            const avg = parseFloat(h.avg_price)||0;
            const mktP = _priceMap[ticker]||0;
            const value = shares * mktP;
            const cost = shares * avg;
            const pnl = shares>0 ? value - cost : null;
            const pnlPct = cost>0&&pnl!=null ? (pnl/cost)*100 : null;
            actualTotal += value;

            const cells = row.querySelectorAll('td');
            // cells: [ticker, target, shares, avg, mktPrice, value, pnl, pnl%, actions]
            if (cells[4]) cells[4].innerHTML = mktP ? `<span class="num">${fmt$(mktP)}</span>` : '—';
            if (cells[5]) cells[5].innerHTML = value ? fmt$(value) : '—';
            if (cells[6]) cells[6].innerHTML = `<span class="${clsPct(pnl)}">${pnl!=null?fmt$(pnl):'—'}</span>`;
            if (cells[7]) cells[7].innerHTML = `<span class="${clsPct(pnlPct)}">${pnlPct!=null?fmtPct(pnlPct):'—'}</span>`;
        });

        // Update bucket header
        const devPct = ta>0 ? ((actualTotal-ta)/ta)*100 : 0;
        const meta = section.querySelector('.bucket-meta');
        if (meta) {
            meta.querySelector('.actual-val').textContent = fmt$(actualTotal);
            const devEl = meta.querySelector('.deviation-pct');
            if (devEl) { devEl.textContent = fmtPct(devPct); devEl.className = 'deviation-pct ' + clsPct(devPct); }
        }
    });
}

function renderPortfolioSettings(pf) {
    const cap = $('#total-capital');
    if (cap) cap.textContent = fmt$(pf.total_capital||0);
    const btd = $('#monthly-btd-budget');
    if (btd) btd.value = pf.monthly_btd_budget||0;
    const rp = $('#rotation-pool');
    if (rp) rp.value = pf.rotation_pool||0;
}

function renderAllBuckets(pf) {
    for (const [bk, bd] of Object.entries(pf.buckets||{})) {
        const section = $(`.bucket-section[data-bucket="${bk}"]`);
        if (!section) continue;
        const holdings = bd.holdings||[];
        const tbody = section.querySelector('.holdings-table tbody');
        if (!tbody) continue;
        tbody.innerHTML = '';

        let actualTotal = 0, targetTotal = 0;
        for (const h of holdings) {
            const shares = parseFloat(h.actual_shares)||0;
            const avg    = parseFloat(h.avg_price)||0;
            const target = parseFloat(h.target_amount)||0;
            const mktP   = _priceMap[h.ticker]||0;
            const value  = shares * mktP;
            const cost   = shares * avg;
            const pnl    = shares>0 ? value - cost : null;
            const pnlPct = cost>0&&pnl!=null ? (pnl/cost)*100 : null;
            actualTotal += value;
            targetTotal += target;

            const tr = document.createElement('tr');
            tr.dataset.ticker = h.ticker;
            tr.dataset.bucket = bk;
            tr.innerHTML = `
                <td><strong>${h.ticker}</strong></td>
                <td class="num">${fmt$(target)}</td>
                <td class="num editable" data-field="actual_shares" data-bucket="${bk}" data-ticker="${h.ticker}">${shares||'—'}</td>
                <td class="num editable" data-field="avg_price" data-bucket="${bk}" data-ticker="${h.ticker}">${avg?fmt$(avg):'—'}</td>
                <td class="num">${mktP?fmt$(mktP):'—'}</td>
                <td class="num">${value?fmt$(value):'—'}</td>
                <td class="num"><span class="${clsPct(pnl)}">${pnl!=null?fmt$(pnl):'—'}</span></td>
                <td class="num"><span class="${clsPct(pnlPct)}">${pnlPct!=null?fmtPct(pnlPct):'—'}</span></td>
                <td>
                    <button class="btn btn-primary btn-sm" onclick="openTradeModal('${bk}','${h.ticker}')">Trade</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteHolding('${bk}','${h.ticker}')">Del</button>
                </td>
            `;
            tbody.appendChild(tr);
        }

        // Wire up click-to-edit on editable cells
        tbody.querySelectorAll('.editable').forEach(cell => {
            cell.addEventListener('click', () => startCellEdit(cell));
        });

        // Update bucket header meta
        const tw = bd.target_weight||0;
        const ta = bd.target_amount||0;
        const devPct = ta>0 ? ((actualTotal-ta)/ta)*100 : 0;
        const meta = section.querySelector('.bucket-meta');
        if (meta) {
            meta.querySelector('.target-pct').textContent = tw;
            meta.querySelector('.target-amt').textContent = fmt$(ta);
            meta.querySelector('.actual-val').textContent = fmt$(actualTotal);
            const devEl = meta.querySelector('.deviation-pct');
            devEl.textContent = fmtPct(devPct);
            devEl.className = 'deviation-pct ' + clsPct(devPct);
        }
    }
}

// ---------------------------------------------------------------------------
// Inline cell editing: click a cell → input appears → blur/Enter saves
// ---------------------------------------------------------------------------
function startCellEdit(cell) {
    if (cell.querySelector('input')) return; // already editing

    const field  = cell.dataset.field;   // 'actual_shares' or 'avg_price'
    const bucket = cell.dataset.bucket;
    const ticker = cell.dataset.ticker;
    const h = (_pfData?.buckets?.[bucket]?.holdings||[]).find(x=>x.ticker===ticker);
    if (!h) return;

    const rawValue = parseFloat(h[field])||0;

    // Replace cell content with an input
    const oldText = cell.textContent;
    cell.innerHTML = '';
    const input = document.createElement('input');
    input.type = 'number';
    input.step = field==='actual_shares' ? '0.0001' : '0.01';
    input.value = rawValue;
    input.className = 'cell-edit-input';
    cell.appendChild(input);
    input.focus();
    input.select();

    const commit = async () => {
        const newVal = parseFloat(input.value)||0;
        // Optimistically update local data
        h[field] = newVal;

        // Re-render this cell with the new value
        if (field==='actual_shares') {
            cell.textContent = newVal || '—';
        } else {
            cell.textContent = newVal ? fmt$(newVal) : '—';
        }

        // Re-attach click listener
        cell.addEventListener('click', () => startCellEdit(cell));

        // Recalculate row value/P&L with new data
        recalcRow(cell.closest('tr'), bucket, ticker);

        // Save to server in background
        try {
            const payload = { bucket, ticker };
            payload[field] = newVal;
            const r = await API.updateHolding(payload);
            if (r.error) { showToast(r.error,'error'); }
        } catch(e) { showToast('Save failed','error'); }
    };

    const cancel = () => {
        if (field==='actual_shares') cell.textContent = rawValue || '—';
        else cell.textContent = rawValue ? fmt$(rawValue) : '—';
        cell.addEventListener('click', () => startCellEdit(cell));
    };

    let committed = false;
    input.addEventListener('blur', () => { if(!committed){ committed=true; commit(); } });
    input.addEventListener('keydown', e => {
        if (e.key==='Enter') { e.preventDefault(); committed=true; commit(); input.blur(); }
        if (e.key==='Escape') { e.preventDefault(); committed=true; cancel(); }
    });
}

/** Recalculate the value/P&L cells for a single row after an inline edit. */
function recalcRow(row, bucket, ticker) {
    if (!row) return;
    const h = (_pfData?.buckets?.[bucket]?.holdings||[]).find(x=>x.ticker===ticker);
    if (!h) return;
    const shares = parseFloat(h.actual_shares)||0;
    const avg    = parseFloat(h.avg_price)||0;
    const mktP   = _priceMap[ticker]||0;
    const value  = shares * mktP;
    const cost   = shares * avg;
    const pnl    = shares>0 ? value - cost : null;
    const pnlPct = cost>0&&pnl!=null ? (pnl/cost)*100 : null;

    const cells = row.querySelectorAll('td');
    // [ticker, target, shares, avg, mktPrice, value, pnl, pnl%, actions]
    if (cells[4]) cells[4].innerHTML = mktP ? fmt$(mktP) : '—';
    if (cells[5]) cells[5].innerHTML = value ? fmt$(value) : '—';
    if (cells[6]) cells[6].innerHTML = `<span class="${clsPct(pnl)}">${pnl!=null?fmt$(pnl):'—'}</span>`;
    if (cells[7]) cells[7].innerHTML = `<span class="${clsPct(pnlPct)}">${pnlPct!=null?fmtPct(pnlPct):'—'}</span>`;

    // Recalculate bucket header totals
    recalcBucketHeader(bucket);
}

function recalcBucketHeader(bucket) {
    const section = $(`.bucket-section[data-bucket="${bucket}"]`);
    if (!section) return;
    const bd = _pfData?.buckets?.[bucket];
    if (!bd) return;

    let actualTotal = 0;
    for (const h of bd.holdings||[]) {
        const shares = parseFloat(h.actual_shares)||0;
        const mktP = _priceMap[h.ticker]||0;
        actualTotal += shares * mktP;
    }
    const ta = bd.target_amount||0;
    const devPct = ta>0 ? ((actualTotal-ta)/ta)*100 : 0;
    const meta = section.querySelector('.bucket-meta');
    if (meta) {
        meta.querySelector('.actual-val').textContent = fmt$(actualTotal);
        const devEl = meta.querySelector('.deviation-pct');
        if (devEl) { devEl.textContent = fmtPct(devPct); devEl.className = 'deviation-pct ' + clsPct(devPct); }
    }
}

// --- Delete Holding ---
async function deleteHolding(bucket, ticker) {
    if (!confirm(`Delete ${ticker} from ${bucket}?`)) return;
    showLoading();
    try {
        const r = await API.deleteHolding({bucket,ticker});
        if(r.error) showToast(r.error,'error'); else { showToast(`${ticker} removed`); await loadPortfolioData(); }
    } catch(e) { showToast('Delete failed','error'); }
    finally { hideLoading(); }
}

// --- Add Holding ---
function showAddHoldingForm(bucket, btn) {
    const section = btn.closest('.bucket-content');
    const form = section?.querySelector('.add-holding-form');
    if (form) form.style.display = 'flex';
}
function hideAddHoldingForm(btn) {
    const form = btn.closest('.add-holding-form');
    if (form) { form.style.display='none'; form.querySelectorAll('input').forEach(i=>i.value=''); }
}

async function addHolding(bucket, btn) {
    const form = btn.closest('.add-holding-form');
    const ticker = form.querySelector('.input-ticker')?.value?.trim().toUpperCase();
    const target = parseFloat(form.querySelector('.input-target-amount')?.value)||0;
    const shares = parseFloat(form.querySelector('.input-shares')?.value)||0;
    const avg    = parseFloat(form.querySelector('.input-avg-price')?.value)||0;
    if (!ticker) { showToast('Ticker required','error'); return; }
    showLoading();
    try {
        const r = await API.addHolding({bucket,ticker,target_amount:target,actual_shares:shares,avg_price:avg});
        if(r.error) showToast(r.error,'error'); else { showToast(`${ticker} added`); await loadPortfolioData(); }
    } catch(e) { showToast('Add failed','error'); }
    finally { hideLoading(); }
}

// --- Options ---
function renderOptionsTable(options) {
    const tbody = $('#options-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    for (const o of options) {
        const totalCost = (parseFloat(o.avg_cost)||0) * (parseInt(o.contracts)||0) * 100;
        const tr = document.createElement('tr');
        tr.dataset.optionId = o.id||'';
        tr.innerHTML = `
            <td><strong>${o.underlying||''}</strong></td>
            <td>${(o.type||'').toUpperCase()}</td>
            <td>${o.tier||''}</td>
            <td class="num">${o.strike?fmt$(o.strike):'—'}</td>
            <td>${o.expiry||'—'}</td>
            <td class="num">${o.contracts||0}</td>
            <td class="num">${o.avg_cost?fmt$(o.avg_cost):'—'}</td>
            <td class="num">${o.delta||'—'}</td>
            <td class="num">${o.dte||'—'}</td>
            <td class="num">${o.budget?fmt$(o.budget):'—'}</td>
            <td class="num">${totalCost?fmt$(totalCost):'—'}</td>
            <td class="text-sm">${o.notes||''}</td>
            <td>
                <button class="btn btn-sm" onclick="editOption('${o.id}',this)">Edit</button>
                <button class="btn btn-danger btn-sm" onclick="deleteOption('${o.id}')">Del</button>
            </td>
        `;
        tbody.appendChild(tr);
    }
}

function editOption(id, btn) {
    const row = btn.closest('tr');
    const o = (_pfData?.options||[]).find(x=>x.id===id);
    if (!o||!row) return;
    row.innerHTML = `
        <td><input type="text" value="${o.underlying||''}" class="ed-underlying" style="width:70px"></td>
        <td><select class="ed-type"><option value="put" ${o.type==='put'?'selected':''}>Put</option><option value="call" ${o.type==='call'?'selected':''}>Call</option></select></td>
        <td><input type="text" value="${o.tier||''}" class="ed-tier" style="width:80px"></td>
        <td><input type="number" value="${o.strike||0}" class="ed-strike" step="any" style="width:70px"></td>
        <td><input type="date" value="${o.expiry||''}" class="ed-expiry" style="width:130px"></td>
        <td><input type="number" value="${o.contracts||0}" class="ed-contracts" step="1" style="width:60px"></td>
        <td><input type="number" value="${o.avg_cost||0}" class="ed-avgcost" step="any" style="width:70px"></td>
        <td><input type="number" value="${o.delta||0}" class="ed-delta" step="any" style="width:60px"></td>
        <td><input type="number" value="${o.dte||0}" class="ed-dte" step="1" style="width:60px"></td>
        <td><input type="number" value="${o.budget||0}" class="ed-budget" step="any" style="width:70px"></td>
        <td></td>
        <td><input type="text" value="${o.notes||''}" class="ed-notes" style="width:120px"></td>
        <td>
            <button class="btn btn-primary btn-sm" onclick="saveOption('${id}',this)">Save</button>
            <button class="btn btn-sm" onclick="loadPortfolioData()">Cancel</button>
        </td>
    `;
}

async function saveOption(id, btn) {
    const row = btn.closest('tr');
    const data = {
        id,
        underlying: row.querySelector('.ed-underlying')?.value?.trim().toUpperCase()||'',
        type: row.querySelector('.ed-type')?.value||'put',
        tier: row.querySelector('.ed-tier')?.value||'',
        strike: parseFloat(row.querySelector('.ed-strike')?.value)||0,
        expiry: row.querySelector('.ed-expiry')?.value||'',
        contracts: parseInt(row.querySelector('.ed-contracts')?.value)||0,
        avg_cost: parseFloat(row.querySelector('.ed-avgcost')?.value)||0,
        delta: parseFloat(row.querySelector('.ed-delta')?.value)||0,
        dte: parseInt(row.querySelector('.ed-dte')?.value)||0,
        budget: parseFloat(row.querySelector('.ed-budget')?.value)||0,
        notes: row.querySelector('.ed-notes')?.value||'',
    };
    showLoading();
    try {
        const r = await API.updateOption(data);
        if(r.error) showToast(r.error,'error'); else { showToast('Option updated'); await loadPortfolioData(); }
    } catch(e) { showToast('Save failed','error'); }
    finally { hideLoading(); }
}

async function deleteOption(id) {
    if (!confirm('Delete this option?')) return;
    showLoading();
    try {
        const r = await API.deleteOption({id});
        if(r.error) showToast(r.error,'error'); else { showToast('Option removed'); await loadPortfolioData(); }
    } catch(e) { showToast('Delete failed','error'); }
    finally { hideLoading(); }
}

function showAddOptionForm() {
    const f = $('#add-option-form');
    if (f) f.style.display = 'block';
}
function hideAddOptionForm() {
    const f = $('#add-option-form');
    if (f) { f.style.display='none'; f.querySelectorAll('input').forEach(i=>i.value=''); }
}

async function addOption() {
    const underlying = $('#opt-underlying')?.value?.trim().toUpperCase();
    if (!underlying) { showToast('Underlying required','error'); return; }
    const data = {
        underlying,
        type: $('#opt-type')?.value||'put',
        tier: $('#opt-tier')?.value||'',
        strike: parseFloat($('#opt-strike')?.value)||0,
        expiry: $('#opt-expiry')?.value||'',
        contracts: parseInt($('#opt-contracts')?.value)||0,
        avg_cost: parseFloat($('#opt-avg-cost')?.value)||0,
        delta: parseFloat($('#opt-delta')?.value)||0,
        budget: parseFloat($('#opt-budget')?.value)||0,
        notes: $('#opt-notes')?.value||'',
    };
    showLoading();
    try {
        const r = await API.addOption(data);
        if(r.error) showToast(r.error,'error'); else { showToast('Option added'); await loadPortfolioData(); }
    } catch(e) { showToast('Add failed','error'); }
    finally { hideLoading(); }
}

// --- Save Settings ---
async function saveSettings() {
    const data = {
        total_capital:      parseFloat($('#total-capital')?.textContent?.replace(/[$,]/g,''))||0,
        monthly_btd_budget: parseFloat($('#monthly-btd-budget')?.value)||0,
        rotation_pool:      parseFloat($('#rotation-pool')?.value)||0,
    };
    showLoading();
    try {
        const r = await API.updateSettings(data);
        if(r.error) showToast(r.error,'error'); else showToast('Settings saved');
    } catch(e) { showToast('Save failed','error'); }
    finally { hideLoading(); }
}

// ---------------------------------------------------------------------------
// ========================  TRADE RECORDING  ===============================
// ---------------------------------------------------------------------------

function openTradeModal(bucket, ticker) {
    const modal = $('#trade-modal');
    if (!modal) return;
    $('#trade-bucket').value = bucket;
    $('#trade-ticker').value = ticker;
    $('#trade-action').value = 'BUY';
    $('#trade-shares').value = '';
    $('#trade-price').value = '';
    $('#trade-fees').value = '';
    $('#trade-notes').value = '';
    // Default date to today
    $('#trade-date').value = new Date().toISOString().split('T')[0];
    // Pre-fill price with market price if available
    if (_priceMap[ticker]) {
        $('#trade-price').value = _priceMap[ticker].toFixed(2);
    }
    $('#trade-preview').style.display = 'none';
    modal.style.display = 'flex';
    $('#trade-shares').focus();

    // Live preview
    const updatePreview = () => {
        const action = $('#trade-action').value;
        const sh = parseFloat($('#trade-shares').value)||0;
        const pr = parseFloat($('#trade-price').value)||0;
        const fees = parseFloat($('#trade-fees').value)||0;
        const preview = $('#trade-preview');
        const text = $('#trade-preview-text');
        if (sh>0 && pr>0) {
            const total = sh*pr + (action==='BUY'?fees:-fees);
            const h = (_pfData?.buckets?.[bucket]?.holdings||[]).find(x=>x.ticker===ticker);
            const oldSh = parseFloat(h?.actual_shares)||0;
            const oldAvg = parseFloat(h?.avg_price)||0;
            let newSh, newAvg;
            if (action==='BUY') {
                newSh = oldSh + sh;
                const effP = pr + (sh>0 ? fees/sh : 0);
                newAvg = newSh>0 ? ((oldSh*oldAvg)+(sh*effP))/newSh : 0;
            } else {
                newSh = Math.max(0, oldSh - sh);
                newAvg = oldAvg;
            }
            text.innerHTML = `<strong>${action} ${sh} ${ticker} @ ${fmt$(pr)}</strong> = ${fmt$(total)}<br>`
                + `Shares: ${oldSh} → ${newSh.toFixed(4)} &nbsp;|&nbsp; Avg: ${fmt$(oldAvg)} → ${fmt$(newAvg)}`;
            preview.style.display = 'block';
        } else {
            preview.style.display = 'none';
        }
    };
    ['trade-action','trade-shares','trade-price','trade-fees'].forEach(id => {
        const el = $(`#${id}`);
        if (el) { el.removeEventListener('input', updatePreview); el.addEventListener('input', updatePreview); }
    });
    // Also listen to action change
    const actionEl = $('#trade-action');
    if (actionEl) { actionEl.removeEventListener('change', updatePreview); actionEl.addEventListener('change', updatePreview); }
}

function closeTradeModal() {
    const modal = $('#trade-modal');
    if (modal) modal.style.display = 'none';
}

async function submitTrade() {
    const bucket = $('#trade-bucket').value;
    const ticker = $('#trade-ticker').value;
    const action = $('#trade-action').value;
    const shares = parseFloat($('#trade-shares').value)||0;
    const price  = parseFloat($('#trade-price').value)||0;
    const fees   = parseFloat($('#trade-fees').value)||0;
    const date   = $('#trade-date').value||'';
    const notes  = $('#trade-notes').value||'';

    if (shares<=0||price<=0) { showToast('Shares and price are required','error'); return; }

    try {
        const r = await API.recordTrade({bucket, ticker, action, shares, price, fees, date, notes});
        if (r.error) { showToast(r.error,'error'); return; }

        // Update local data from server response
        _pfData = r.portfolio;
        showToast(`${action} ${shares} ${ticker} @ ${fmt$(price)} recorded`);
        closeTradeModal();

        // Re-render portfolio with updated data
        renderPortfolioSettings(_pfData);
        renderAllBuckets(_pfData);
        renderOptionsTable(_pfData.options||[]);
        renderTradeLog(_pfData.trades||[]);

        // Re-patch live prices
        patchLivePrices();
    } catch(e) { showToast('Trade failed','error'); console.error(e); }
}

function renderTradeLog(trades) {
    const tbody = $('#trade-log-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const bucketNames = { tech_stocks:'Tech', growth_etfs:'Growth', defensive_etfs:'Defensive', gold_silver:'Gold/Silver', hedges:'Hedges' };

    if (!trades || trades.length===0) {
        tbody.innerHTML = '<tr><td colspan="11" class="text-muted text-sm" style="text-align:center">No trades recorded yet. Click "Trade" on any holding to log a transaction.</td></tr>';
        return;
    }

    for (const t of trades) {
        const total = (parseFloat(t.shares)||0) * (parseFloat(t.price)||0);
        const isBuy = t.action==='BUY';
        const tr = document.createElement('tr');
        tr.className = isBuy ? 'trade-buy' : 'trade-sell';
        tr.innerHTML = `
            <td>${t.date||'—'}</td>
            <td><span class="badge ${isBuy?'badge-btd':'badge-str'}">${t.action}</span></td>
            <td><strong>${t.ticker}</strong></td>
            <td class="num">${t.shares}</td>
            <td class="num">${fmt$(t.price)}</td>
            <td class="num">${fmt$(total)}</td>
            <td class="num">${t.fees?fmt$(t.fees):'—'}</td>
            <td class="num">${t.resulting_shares??'—'}</td>
            <td class="num">${t.resulting_avg!=null?fmt$(t.resulting_avg):'—'}</td>
            <td class="text-sm">${t.notes||''}</td>
            <td><button class="btn btn-danger btn-sm" onclick="deleteTrade('${t.id}')">Del</button></td>
        `;
        tbody.appendChild(tr);
    }
}

async function deleteTrade(id) {
    if (!confirm('Remove this trade log entry? (Does not reverse shares/avg changes)')) return;
    try {
        const r = await API.deleteTrade({id});
        if (r.error) { showToast(r.error,'error'); return; }
        _pfData = r;
        renderTradeLog(_pfData.trades||[]);
        showToast('Trade log entry removed');
    } catch(e) { showToast('Delete failed','error'); }
}

// ---------------------------------------------------------------------------
// ========================  SUMMARY PAGE  ==================================
// ---------------------------------------------------------------------------

let _allocChart = null;

// On page load: use cached data. Refresh button clears cache.
async function loadSummary() {
    if (!$('.summary-page') && !$('#allocation-chart')) return;
    showLoading();
    try {
        const [summary, mkt, pf] = await Promise.all([API.getSummary(), API.getMarketData(), API.getPortfolio()]);
        renderSummaryCards(summary, pf);
        renderAllocChart(summary);
        renderAllocTable(summary);
        renderScenarios(summary);
        renderActionItems(mkt, pf);
    } catch(e) { console.error(e); showToast('Failed to load summary','error'); }
    finally { hideLoading(); }
}

async function refreshSummary() {
    if (!$('.summary-page') && !$('#allocation-chart')) return;
    showLoading();
    try {
        await API.clearCache();
        const [summary, mkt, pf] = await Promise.all([API.getSummary(), API.getMarketData(), API.getPortfolio()]);
        renderSummaryCards(summary, pf);
        renderAllocChart(summary);
        renderAllocTable(summary);
        renderScenarios(summary);
        renderActionItems(mkt, pf);
        showToast('Summary refreshed');
    } catch(e) { console.error(e); showToast('Failed to load summary','error'); }
    finally { hideLoading(); }
}

function renderSummaryCards(s, pf) {
    const tv = $('#total-value');
    if (tv) tv.querySelector('.card-value').textContent = fmt$(s.total_actual);

    const totalCost = s.total_capital||0;
    const pnl = s.total_actual - totalCost;
    const pnlPct = totalCost>0 ? (pnl/totalCost)*100 : 0;
    const tpnl = $('#total-pnl');
    if (tpnl) {
        const cv = tpnl.querySelector('.card-value');
        cv.textContent = fmt$(pnl);
        cv.className = 'card-value ' + clsPct(pnl);
        const cp = tpnl.querySelector('.card-pct');
        if (cp) { cp.textContent = fmtPct(pnlPct); cp.className = 'card-pct ' + clsPct(pnlPct); }
    }

    const yieldRates = {SCHD:0.035, JEPQ:0.09, DGRO:0.025, PFF:0.06, ALLW:0.04};
    let annualIncome = 0;
    for (const h of (pf.buckets?.defensive_etfs?.holdings||[])) {
        const shares = parseFloat(h.actual_shares)||0;
        const price = _priceMap?.[h.ticker]||0;
        annualIncome += shares * price * (yieldRates[h.ticker]||0.03);
    }
    const mi = $('#monthly-income');
    if (mi) mi.querySelector('.card-value').textContent = fmt$(annualIncome/12);

    let monthlyTheta = 0;
    for (const o of (pf.options||[])) {
        const cost = (parseFloat(o.avg_cost)||0) * (parseInt(o.contracts)||0) * 100;
        const dte = parseInt(o.dte)||90;
        monthlyTheta += (cost / Math.max(dte,1)) * 30 * 0.7;
    }
    const tc = $('#theta-cost');
    if (tc) { const cv=tc.querySelector('.card-value'); cv.textContent=fmt$(monthlyTheta); cv.className='card-value negative'; }
}

function renderAllocChart(s) {
    const canvas = $('#allocation-chart');
    if (!canvas || typeof Chart==='undefined') return;

    const colors = {tech_stocks:'#58a6ff', growth_etfs:'#3fb950', defensive_etfs:'#d29922', gold_silver:'#e3b341', hedges:'#f85149'};
    const labels=[], values=[], bgColors=[];

    for (const [bk, bd] of Object.entries(s.buckets||{})) {
        labels.push(bd.name||bk);
        values.push(bd.actual_value||0);
        bgColors.push(colors[bk]||'#8b949e');
    }

    if (_allocChart) { _allocChart.destroy(); _allocChart=null; }
    if (values.every(v=>v===0)) {
        for (let i=0; i<values.length; i++) {
            values[i] = Object.values(s.buckets)[i]?.target_amount || 0;
        }
    }

    _allocChart = new Chart(canvas, {
        type: 'doughnut',
        data: { labels, datasets: [{ data:values, backgroundColor:bgColors, borderColor:'#161b22', borderWidth:2 }] },
        options: {
            responsive:true, maintainAspectRatio:false,
            plugins: {
                legend: { position:'bottom', labels:{ color:'#8b949e', padding:12, font:{size:12} } },
                tooltip: { callbacks: { label: ctx => {
                    const tot = ctx.dataset.data.reduce((a,b)=>a+b,0);
                    const pct = tot>0?((ctx.parsed/tot)*100).toFixed(1):0;
                    return `${ctx.label}: ${fmt$(ctx.parsed)} (${pct}%)`;
                }}}
            },
            cutout: '60%',
        }
    });
}

function renderAllocTable(s) {
    const tbody = $('#allocation-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    let totTarget=0, totActual=0;

    for (const [bk, bd] of Object.entries(s.buckets||{})) {
        const target = bd.target_amount||0;
        const actual = bd.actual_value||0;
        const dev = actual - target;
        const devPct = target>0 ? (dev/target)*100 : 0;
        const tw = {tech_stocks:22, growth_etfs:25, defensive_etfs:25, gold_silver:23, hedges:5}[bk]||0;
        totTarget += target;
        totActual += actual;

        tbody.innerHTML += `<tr>
            <td>${bd.name||bk}</td>
            <td class="num">${tw}%</td>
            <td class="num">${fmt$(target)}</td>
            <td class="num">${fmt$(actual)}</td>
            <td class="num"><span class="${clsPct(dev)}">${fmt$(dev)}</span></td>
            <td class="num"><span class="${clsPct(devPct)}">${fmtPct(devPct)}</span></td>
        </tr>`;
    }
    const totDev = totActual-totTarget;
    const totDevPct = totTarget>0?(totDev/totTarget)*100:0;
    tbody.innerHTML += `<tr style="font-weight:600;border-top:2px solid #30363d">
        <td>Total</td><td class="num">100%</td>
        <td class="num">${fmt$(totTarget)}</td><td class="num">${fmt$(totActual)}</td>
        <td class="num"><span class="${clsPct(totDev)}">${fmt$(totDev)}</span></td>
        <td class="num"><span class="${clsPct(totDevPct)}">${fmtPct(totDevPct)}</span></td>
    </tr>`;
}

function renderScenarios(s) {
    const scenarios = s.scenarios||{};
    const mapping = {
        'scenario-bull': scenarios.bull_5pct,
        'scenario-bear': scenarios.bear_5pct,
        'scenario-crash': scenarios.crash_10pct,
    };

    for (const [cardId, sc] of Object.entries(mapping)) {
        const card = $(`#${cardId}`);
        if (!card || !sc) continue;
        const totalVal = s.total_actual||0;
        const eqChange = sc.total_change||0;
        const hedgePnl = sc.hedge_pnl||0;
        const netChange = sc.net_change||0;
        const newVal = totalVal + netChange;

        const eq = card.querySelector('[data-field="equity-change"]');
        if (eq) { eq.textContent=fmt$(eqChange); eq.className='scenario-val '+clsPct(eqChange); }
        const hp = card.querySelector('[data-field="hedge-pnl"]');
        if (hp) { hp.textContent=fmt$(hedgePnl); hp.className='scenario-val '+clsPct(hedgePnl); }
        const nc = card.querySelector('[data-field="net-change"]');
        if (nc) { nc.textContent=fmt$(netChange); nc.className='scenario-val '+clsPct(netChange); }
        const nv = card.querySelector('[data-field="new-value"]');
        if (nv) { nv.textContent=fmt$(newVal); }
    }
}

function renderActionItems(mkt, pf) {
    const tbody = $('#action-items-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';

    const data = mkt.data||{};
    const bucketMap = {};
    const bucketNames = { tech_stocks:'Tech Stocks', growth_etfs:'Growth ETFs', defensive_etfs:'Defensive ETFs', gold_silver:'Gold & Silver', hedges:'Hedges' };
    for (const [bk, bd] of Object.entries(pf.buckets||{})) {
        for (const h of bd.holdings||[]) bucketMap[h.ticker] = bk;
    }

    for (const [ticker, d] of Object.entries(data)) {
        const sig = d.signal;
        if (!sig || sig.action==='HOLD') continue;
        const bucket = bucketMap[ticker]||'';
        const holding = (pf.buckets?.[bucket]?.holdings||[]).find(h=>h.ticker===ticker);
        const targetAmt = holding?.target_amount||0;
        const trimPct = sig.trim_pct||0;
        const estAmt = sig.action==='STR' ? targetAmt*trimPct : 0;

        tbody.innerHTML += `<tr class="${signalRowCls(sig)}">
            <td>${signalBadge(sig)}</td>
            <td><strong>${ticker}</strong></td>
            <td class="text-sm">${bucketNames[bucket]||bucket}</td>
            <td class="num"><span class="${clsPct(d.div_sma)}">${fmtPct(d.div_sma)}</span></td>
            <td class="text-sm">${sig.label||''}</td>
            <td class="num">${estAmt?fmt$(estAmt):'—'}</td>
        </tr>`;
    }

    if (!tbody.children.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-muted text-sm" style="text-align:center">No action items</td></tr>';
    }
}
