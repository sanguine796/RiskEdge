// History page JS: handles fetching, rendering, sorting, pagination, filtering, and export
// Production-quality, vanilla JS with accessibility in mind

(() => {
  let currentAPI = '/api/all_history';
  let predictionType = 'all'; // 'all', 'default' or 'approval'
  const pageSize = 10;
  let rawList = [];
  let filtered = [];
  let page = 1;
  let sortKey = 'created';
  let sortDir = -1; // -1 desc, 1 asc

  const el = {
    predictionTypeFilter: document.getElementById('predictionTypeFilter'),
    search: document.getElementById('searchInput'),
    riskFilter: document.getElementById('riskFilter'),
    statusFilter: document.getElementById('statusFilter'),
    riskFilterContainer: document.getElementById('riskFilterContainer'),
    statusFilterContainer: document.getElementById('statusFilterContainer'),
    clearSearch: document.getElementById('clearSearch'),
    refresh: document.getElementById('refreshBtn'),
    export: document.getElementById('exportBtn'),
    tableBody: document.getElementById('tableBody'),
    prev: document.getElementById('prevPage'),
    next: document.getElementById('nextPage'),
    pageInfo: document.getElementById('pageInfo'),
    emptyState: document.getElementById('emptyState'),
    kpiTotal: document.getElementById('kpiTotal'),
    kpiApproved: document.getElementById('kpiApproved'),
    kpiRejected: document.getElementById('kpiRejected'),
    kpiDefault: document.getElementById('kpiDefault'),
    kpiNonDefault: document.getElementById('kpiNonDefault')
  };

  function setPredictionType(type) {
    predictionType = type;
    currentAPI = type === 'approval' ? '/api/approval_history' : type === 'default' ? '/api/history' : '/api/all_history';
    
    // Update UI visibility and filter options
    if (type === 'approval') {
      el.riskFilterContainer.style.display = 'none';
      // Update status filter options for approval
      el.statusFilter.innerHTML = `
        <option value="">All Decisions</option>
        <option value="approve">Approved</option>
        <option value="reject">Rejected</option>
      `;
      el.statusFilterContainer.style.display = 'block';
    } else if (type === 'default') {
      el.riskFilterContainer.style.display = 'block';
      // Update status filter options for default
      el.statusFilter.innerHTML = `
        <option value="">All Status</option>
        <option value="default">Default</option>
        <option value="non-default">Non-Default</option>
      `;
      el.statusFilterContainer.style.display = 'block';
    } else {
      el.riskFilterContainer.style.display = 'none';
      el.statusFilter.innerHTML = `
        <option value="">All Status</option>
        <option value="default">Default</option>
        <option value="non-default">Non-Default</option>
        <option value="approve">Approved</option>
        <option value="reject">Rejected</option>
      `;
      el.statusFilterContainer.style.display = 'block';
    }
  }

  function showSkeletons(count = 6) {
    el.tableBody.innerHTML = '';
    const tpl = document.getElementById('skeletonRow');
    for (let i = 0; i < count; i++) {
      const clone = tpl.content.cloneNode(true);
      el.tableBody.appendChild(clone);
    }
  }

  function formatDate(s) {
    try { return new Date(s).toLocaleString(); } catch(e) { return s; }
  }

  function badgeFor(risk) {
    if (!risk) return `<span class="badge-risk low">Unknown</span>`;
    const key = risk.toLowerCase();
    if (key === 'high') return `<span class="badge-risk high">⚠ High</span>`;
    if (key === 'medium') return `<span class="badge-risk medium">⚡ Medium</span>`;
    return `<span class="badge-risk low">✓ Low</span>`;
  }

  function normalizeLabel(value) {
    const text = String(value || '').trim().toLowerCase();
    if (!text) return '';
    if (text.includes('approved') || text === 'approve' || text === 'loan approved') return 'approved';
    if (text.includes('rejected') || text === 'reject' || text === 'loan rejected') return 'rejected';
    if (text === 'default') return 'default';
    if (text === 'non-default' || text === 'non default' || text === 'nondefault') return 'non-default';
    return text;
  }

  function classifyItem(item) {
    const type = String(item.prediction_type || item.type || '').trim().toLowerCase();
    const label = normalizeLabel(item.predicted_label || item.label);
    if (type === 'approval' || label === 'approved' || label === 'rejected') {
      return { kind: 'approval', label };
    }
    if (type === 'default' || label === 'default' || label === 'non-default') {
      return { kind: 'default', label };
    }
    return { kind: 'other', label };
  }

  function renderStats(list) {
    const total = list.length;
    const approved = list.filter(i => classifyItem(i).kind === 'approval' && classifyItem(i).label === 'approved').length;
    const rejected = list.filter(i => classifyItem(i).kind === 'approval' && classifyItem(i).label === 'rejected').length;
    const defaults = list.filter(i => classifyItem(i).kind === 'default' && classifyItem(i).label === 'default').length;
    const nonDefaults = list.filter(i => classifyItem(i).kind === 'default' && classifyItem(i).label === 'non-default').length;

    el.kpiTotal.querySelector('.value').textContent = total;
    el.kpiApproved.querySelector('.value').textContent = approved;
    el.kpiRejected.querySelector('.value').textContent = rejected;
    el.kpiDefault.querySelector('.value').textContent = defaults;
    el.kpiNonDefault.querySelector('.value').textContent = nonDefaults;
  }

  function applyFilter() {
    const q = el.search.value.trim().toLowerCase();
    const riskVal = el.riskFilter.value.trim().toLowerCase();
    const statusVal = el.statusFilter.value.trim().toLowerCase();

    filtered = rawList.filter(it => {
      // Text search
      const matchesText = !q || 
        (it.customer_id||'').toString().toLowerCase().includes(q) ||
        (it.name||'').toLowerCase().includes(q) ||
        (it.label||it.predicted_label||'').toLowerCase().includes(q) ||
        (it.risk_category||'').toLowerCase().includes(q);

      // Risk filter (for default predictions only)
        const matchesRisk = !riskVal || predictionType === 'all' || predictionType !== 'default' ||
        (it.risk_category||'').toLowerCase() === riskVal;

      // Status filter
      let matchesStatus = true;
      if (statusVal) {
        const label = (it.label || it.predicted_label || '').toLowerCase();
        if (predictionType === 'default') {
          matchesStatus = (statusVal === 'default' && label === 'default') ||
                         (statusVal === 'non-default' && label !== 'default');
        } else if (predictionType === 'approval') {
          matchesStatus = (statusVal === 'approve' && label === 'approved') ||
                         (statusVal === 'reject' && label === 'rejected');
        } else {
          matchesStatus = (statusVal === 'default' && label === 'default') ||
                         (statusVal === 'non-default' && label !== 'default') ||
                         (statusVal === 'approve' && label === 'approved') ||
                         (statusVal === 'reject' && label === 'rejected');
        }
      }

      return matchesText && matchesRisk && matchesStatus;
    });
  }

  function applySort() {
    filtered.sort((a,b) => {
      const va = (a[sortKey] == null) ? '' : a[sortKey];
      const vb = (b[sortKey] == null) ? '' : b[sortKey];
      if (typeof va === 'string') return sortDir * va.localeCompare(vb);
      return sortDir * ((va > vb) - (va < vb));
    });
  }

  function renderTable() {
    el.tableBody.innerHTML = '';
    if (!filtered.length) {
      el.emptyState.hidden = false;
      el.pageInfo.textContent = '0 / 0';
      return;
    }
    el.emptyState.hidden = true;
    applySort();
    const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
    if (page > totalPages) page = totalPages;

    const start = (page-1)*pageSize;
    const pageItems = filtered.slice(start, start+pageSize);

    pageItems.forEach((it, idx) => {
      const serialNo = start + idx + 1;
      const row = document.createElement('div');
      row.className = 'history-row';
      row.style.display = 'flex';
      row.style.alignItems = 'center';
      row.style.borderBottom = '1px solid var(--border)';
      row.style.padding = '12px 0';
      
      // Serial Number Cell
      const serialCell = document.createElement('div');
      serialCell.className = 'cell';
      serialCell.style.width = '8%';
      serialCell.style.textAlign = 'center';
      serialCell.style.flexShrink = 0;
      serialCell.textContent = serialNo;
      
      // Customer Name Cell
      const customerCell = document.createElement('div');
      customerCell.className = 'cell';
      customerCell.style.width = '22%';
      customerCell.style.flexShrink = 0;
      customerCell.textContent = it.name || it.customer_id || 'N/A';
      
      // Prediction Type Cell
      const typeCell = document.createElement('div');
      typeCell.className = 'cell';
      typeCell.style.width = '18%';
      typeCell.style.flexShrink = 0;
      const typeBadge = (it.prediction_type || predictionType) === 'approval' 
        ? '<span class="badge bg-info" style="white-space: nowrap;">Approval</span>'
        : '<span class="badge bg-primary" style="white-space: nowrap;">Default</span>';
      typeCell.innerHTML = typeBadge;
      
      // Risk Category / Decision Cell
      const riskCell = document.createElement('div');
      riskCell.className = 'cell';
      riskCell.style.width = '18%';
      riskCell.style.flexShrink = 0;
      if ((it.prediction_type || predictionType) === 'approval') {
        const decisionBadge = (it.predicted_label||'').toLowerCase() === 'approved'
          ? '<span class="badge bg-success" style="white-space: nowrap;">✅ Approved</span>'
          : '<span class="badge bg-danger" style="white-space: nowrap;">❌ Rejected</span>';
        riskCell.innerHTML = decisionBadge;
      } else {
        riskCell.innerHTML = badgeFor(it.risk_category);
      }
      
      // Probability Cell
      const probCell = document.createElement('div');
      probCell.className = 'cell';
      probCell.style.width = '15%';
      probCell.style.flexShrink = 0;
      probCell.textContent = ((it.probability || 0) * 100).toFixed(1) + '%';
      
      // Created Date Cell
      const dateCell = document.createElement('div');
      dateCell.className = 'cell';
      dateCell.style.width = '19%';
      dateCell.style.flexShrink = 0;
      dateCell.textContent = formatDate(it.created_at);
      
      row.appendChild(serialCell);
      row.appendChild(customerCell);
      row.appendChild(typeCell);
      row.appendChild(riskCell);
      row.appendChild(probCell);
      row.appendChild(dateCell);
      
      el.tableBody.appendChild(row);
    });

    el.pageInfo.textContent = `${page} / ${totalPages}`;
  }

  function viewDetails(item) {
    // Show details in modal or expanded view
    alert(`Details for ${item.name || item.customer_id}:\n\nRisk: ${item.risk_category}\nProbability: ${(item.probability*100).toFixed(1)}%\nScore: ${item.risk_score}\nCreated: ${item.created_at}`);
  }

  function exportToCSV() {
    if (!filtered.length) {
      alert('No data to export');
      return;
    }

    // Create CSV headers based on prediction type
    let headers, rows;
    
    if (predictionType === 'approval') {
      headers = ['ID', 'Customer ID', 'Customer Name', 'Decision', 'Approval Score', 'Probability (%)', 'Created At'];
      rows = filtered.map(it => [
        it.id,
        it.customer_id || '',
        it.name || '',
        it.predicted_label || '',
        it.approval_score || '',
        ((it.probability || 0) * 100).toFixed(1),
        it.created_at || ''
      ]);
    } else if (predictionType === 'default') {
      headers = ['ID', 'Customer ID', 'Customer Name', 'Risk Category', 'Probability (%)', 'Risk Score', 'Prediction', 'Created At'];
      rows = filtered.map(it => [
        it.id,
        it.customer_id || '',
        it.name || '',
        it.risk_category || '',
        ((it.probability || 0) * 100).toFixed(1),
        it.risk_score || '',
        it.label || '',
        it.created_at || ''
      ]);
    } else {
      headers = ['ID', 'Prediction Type', 'Customer ID', 'Customer Name', 'Decision / Risk Category', 'Probability (%)', 'Score', 'Created At'];
      rows = filtered.map(it => [
        it.id,
        it.prediction_type || 'default',
        it.customer_id || '',
        it.name || '',
        it.risk_category || it.predicted_label || '',
        ((it.probability || 0) * 100).toFixed(1),
        it.approval_score ?? it.risk_score ?? '',
        it.created_at || ''
      ]);
    }

    // Convert to CSV string
    const csv = [
      headers.join(','),
      ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
    ].join('\n');

    // Download CSV
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${predictionType}_predictions_${new Date().toISOString().slice(0,10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function load() {
    showSkeletons(6);
    try {
      const res = await fetch(currentAPI, {cache: 'no-store'});
      const data = await res.json();
      rawList = Array.isArray(data) ? data : (data.items || []);
      if (!rawList) rawList = [];
      if (!Array.isArray(data) && data.meta) rawList.meta = data.meta;

      applyFilter();
      renderStats(rawList);
      renderTable();
    } catch (e) {
      el.tableBody.innerHTML = '<div class="text-muted">Failed to load history.</div>';
      console.error(e);
    }
  }

  // debounce helper
  function debounce(fn, wait=250) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(()=>fn(...args), wait); };
  }

  // Wire events
  el.predictionTypeFilter.addEventListener('change', () => { 
    setPredictionType(el.predictionTypeFilter.value); 
    page = 1; 
    load(); 
  });
  el.refresh.addEventListener('click', () => { page = 1; load(); });
  el.export.addEventListener('click', exportToCSV);
  el.clearSearch.addEventListener('click', () => { el.search.value=''; el.search.dispatchEvent(new Event('input')); });
  el.prev.addEventListener('click', () => { if (page>1) { page--; renderTable(); } });
  el.next.addEventListener('click', () => { const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize)); if (page<totalPages) { page++; renderTable(); } });

  el.search.addEventListener('input', debounce(() => { page = 1; applyFilter(); renderTable(); }, 200));
  el.riskFilter.addEventListener('change', () => { page = 1; applyFilter(); renderTable(); });
  el.statusFilter.addEventListener('change', () => { page = 1; applyFilter(); renderTable(); });

  // sorting buttons
  document.querySelectorAll('.sort-btn').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      const key = btn.dataset.key;
      const newKey = key === 'customer' ? 'name' : key;
      if (sortKey === newKey) {
        sortDir = -sortDir;
      } else {
        sortKey = newKey;
        sortDir = -1;
      }
      page = 1;
      renderTable();
    });
  });

  // keyboard navigation
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight') el.next.click();
    if (e.key === 'ArrowLeft') el.prev.click();
  });

  // initial load
  setPredictionType('all');
  load();
})();
