// Chart.js instances
let riskDistributionChart = null;
let defaultChart = null;
let approvalChart = null;

// Color scheme matching the dark theme
const chartColors = {
    primary: '#4d80f5',
    success: '#36d6a8',
    warning: '#ffc542',
    danger: '#ff6b72',
    text: '#f3f7ff',
    muted: '#9eb7d8'
};

// Initialize dashboard on page load
document.addEventListener('DOMContentLoaded', function () {
    // Set default dates (last 30 days)
    setDefaultDates();
    
    // Load dashboard data
    loadDashboardData();
    
    // Add event listeners
    document.getElementById('refreshBtn').addEventListener('click', loadDashboardData);
    document.getElementById('exportPdfBtn').addEventListener('click', exportPDF);
    document.getElementById('fromDate').addEventListener('change', loadDashboardData);
    document.getElementById('toDate').addEventListener('change', loadDashboardData);
});

window.addEventListener('storage', function (event) {
    if (event.key === 'loan_dashboard_refresh') {
        loadDashboardData();
    }
});

window.addEventListener('dashboard:refresh', function () {
    loadDashboardData();
});

/**
 * Set default date range (last 30 days)
 */
function setDefaultDates() {
    const toDate = new Date();
    const fromDate = new Date();
    fromDate.setDate(toDate.getDate() - 30);
    
    // Format dates as YYYY-MM-DD
    const formatDate = (date) => {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    };
    
    // Set to current date range (all data if not set)
    // You can uncomment below to set default range
    // document.getElementById('fromDate').value = formatDate(fromDate);
    // document.getElementById('toDate').value = formatDate(toDate);
}

/**
 * Load dashboard data from API and update all components
 */
async function loadDashboardData() {
    try {
        // Show loading state
        showLoading(true);
        
        // Get date parameters
        const fromDate = document.getElementById('fromDate').value;
        const toDate = document.getElementById('toDate').value;
        
        // Build query parameters
        let url = '/api/dashboard_data';
        const params = new URLSearchParams();
        if (fromDate) params.append('from_date', fromDate);
        if (toDate) params.append('to_date', toDate);
        if (params.toString()) url += '?' + params.toString();
        
        // Fetch data
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error('Failed to load dashboard data');
        }
        
        const data = await response.json();
        
        // Update KPI cards
        updateKPICards(data);
        
        // Update charts
        updateCharts(data);
        
        // Update recent predictions table
        updateRecentPredictions(data.recent_predictions);
        
        showLoading(false);
        
    } catch (error) {
        console.error('Error loading dashboard data:', error);
        showLoading(false);
        showError('Failed to load dashboard data. Please try again.');
    }
}

/**
 * Update KPI card values
 */
function updateKPICards(data) {
    // Default Risk Predictions
    document.getElementById('totalPredictions').textContent = data.total_predictions || 0;
    document.getElementById('averageRiskScore').textContent = data.average_risk_score || 0;
    document.getElementById('modelAccuracy').textContent = (data.model_accuracy || 0) + '%';
    document.getElementById('highRiskBorrowers').textContent = data.high_risk_borrowers || 0;
    document.getElementById('mediumRiskBorrowers').textContent = data.medium_risk_borrowers || 0;
    document.getElementById('lowRiskBorrowers').textContent = data.low_risk_borrowers || 0;
    
    // Approval Decisions
    const totalApprovals = data.total_approvals || 0;
    const approvedCount = data.approved_count || 0;
    const approvalRate = totalApprovals > 0 ? Math.round((approvedCount / totalApprovals) * 100) : 0;
    
    document.getElementById('totalApprovals').textContent = totalApprovals;
    document.getElementById('approvedCount').textContent = approvedCount;
    document.getElementById('rejectedCount').textContent = data.rejected_count || 0;
    document.getElementById('approvalRate').textContent = approvalRate + '%';
    document.getElementById('avgApprovalScore').textContent = (data.avg_approval_score || 0) + ' pts';
}

/**
 * Update all charts
 */
function updateCharts(data) {
    // Destroy existing charts if they exist
    if (riskDistributionChart) riskDistributionChart.destroy();
    if (defaultChart) defaultChart.destroy();
    if (approvalChart) approvalChart.destroy();
    
    // Create Risk Distribution Doughnut Chart
    createRiskDistributionChart(data.risk_distribution);
    
    // Create Default vs Non-Default Doughnut Chart
    createDefaultChart(data.default_vs_non_default);
    
    // Create Approval vs Rejection Chart
    createApprovalChart(data.approval_vs_rejection);
}

/**
 * Create Risk Distribution Doughnut Chart
 */
function createRiskDistributionChart(riskData) {
    const ctx = document.getElementById('riskDistributionChart').getContext('2d');
    
    riskDistributionChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['High Risk', 'Medium Risk', 'Low Risk'],
            datasets: [{
                data: [
                    riskData.High || 0,
                    riskData.Medium || 0,
                    riskData.Low || 0
                ],
                backgroundColor: [
                    chartColors.danger,
                    chartColors.warning,
                    chartColors.success
                ],
                borderColor: 'rgba(7, 18, 40, 1)',
                borderWidth: 2,
                borderRadius: 4,
                hoverOffset: 8
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: chartColors.text,
                        font: { size: 12, weight: '600' },
                        padding: 15,
                        usePointStyle: true,
                        pointStyle: 'circle'
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: chartColors.text,
                    bodyColor: chartColors.text,
                    padding: 12,
                    displayColors: true,
                    borderColor: chartColors.primary,
                    borderWidth: 1,
                    callbacks: {
                        label: function (context) {
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((context.parsed / total) * 100).toFixed(1);
                            return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                        }
                    }
                }
            }
        }
    });
}

/**
 * Create Default vs Non-Default Doughnut Chart
 */
function createDefaultChart(defaultData) {
    const ctx = document.getElementById('defaultChart').getContext('2d');
    
    defaultChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Defaults', 'Non-Defaults'],
            datasets: [{
                data: [
                    defaultData.defaults || 0,
                    defaultData.non_defaults || 0
                ],
                backgroundColor: [
                    chartColors.danger,
                    chartColors.success
                ],
                borderColor: 'rgba(7, 18, 40, 1)',
                borderWidth: 2,
                borderRadius: 4,
                hoverOffset: 8
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: chartColors.text,
                        font: { size: 12, weight: '600' },
                        padding: 15,
                        usePointStyle: true,
                        pointStyle: 'circle'
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: chartColors.text,
                    bodyColor: chartColors.text,
                    padding: 12,
                    displayColors: true,
                    borderColor: chartColors.primary,
                    borderWidth: 1,
                    callbacks: {
                        label: function (context) {
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((context.parsed / total) * 100).toFixed(1);
                            return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                        }
                    }
                }
            }
        }
    });
}

/**
 * Update Recent Predictions Table with both default and approval predictions
 */
function updateRecentPredictions(predictions) {
    const tbody = document.getElementById('recentPredictionsList');
    
    if (!predictions || predictions.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-muted">No predictions found for selected date range</td></tr>`;
        return;
    }
    
    tbody.innerHTML = predictions.map(pred => {
        let typeLabel = '';
        let resultBadge = '';
        let scoreValue = '';
        
        if (pred.type === 'default') {
            typeLabel = 'Default Risk';
            resultBadge = getRiskBadge(pred.risk_category);
            scoreValue = pred.risk_score;
        } else {
            typeLabel = 'Approval';
            const approved = ['Approve', 'Approved'].includes(pred.predicted_label);
            resultBadge = `<span class="badge ${approved ? 'bg-success' : 'bg-danger'}">${approved ? '✅ Approved' : '❌ Rejected'}</span>`;
            scoreValue = pred.approval_score;
        }
        
        return `
            <tr>
                <td>
                    <span class="customer-name">${escapeHtml(pred.name)}</span>
                </td>
                <td>
                    <span class="badge bg-primary">${typeLabel}</span>
                </td>
                <td>
                    ${resultBadge}
                </td>
                <td>
                    <span class="probability">${pred.probability}%</span>
                </td>
                <td>
                    <span class="score">${scoreValue}</span>
                </td>
                <td>
                    <span class="created-date">${escapeHtml(pred.created_at)}</span>
                </td>
            </tr>
        `;
    }).join('');
}

/**
 * Get prediction label badge HTML
 */
function getPredictionBadge(label) {
    const isDefault = label === 'Default';
    const bgClass = isDefault ? 'badge-default' : 'badge-non-default';
    const icon = isDefault ? '⚠️' : '✅';
    return `<span class="badge ${bgClass}">${icon} ${escapeHtml(label)}</span>`;
}

/**
 * Get risk category badge HTML
 */
function getRiskBadge(category) {
    let bgClass = 'badge-low';
    let icon = '✅';
    
    if (category === 'High') {
        bgClass = 'badge-high';
        icon = '⚠️';
    } else if (category === 'Medium') {
        bgClass = 'badge-medium';
        icon = '⚡';
    }
    
    return `<span class="badge ${bgClass}">${icon} ${escapeHtml(category)}</span>`;
}

/**
 * Export dashboard data as PDF
 */
function exportPDF() {
    const fromDate = document.getElementById('fromDate').value || '';
    const toDate = document.getElementById('toDate').value || '';
    
    // Create download URL with parameters
    let url = '/api/export_pdf';
    const params = new URLSearchParams();
    if (fromDate) params.append('from_date', fromDate);
    if (toDate) params.append('to_date', toDate);
    if (params.toString()) url += '?' + params.toString();
    
    // Trigger download
    const link = document.createElement('a');
    link.href = url;
    link.download = `loan_predictions_${new Date().toISOString().split('T')[0]}.pdf`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

/**
 * Show/hide loading state
 */
function showLoading(show) {
    const tbody = document.getElementById('recentPredictionsList');
    if (show) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-4">
                    <div class="spinner-border spinner-border-sm" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                    Loading predictions...
                </td>
            </tr>
        `;
    }
}

/**
 * Show error message
 */
function showError(message) {
    const tbody = document.getElementById('recentPredictionsList');
    tbody.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-danger">${escapeHtml(message)}</td></tr>`;
}

/**
 * Escape HTML special characters
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Create Approval vs Rejection Doughnut Chart
 */
function createApprovalChart(approvalData) {
    const ctx = document.getElementById('approvalChart').getContext('2d');
    
    approvalChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: ['Approved', 'Rejected'],
            datasets: [{
                data: [approvalData.approved || 0, approvalData.rejected || 0],
                backgroundColor: [
                    chartColors.success,
                    chartColors.danger
                ],
                borderColor: 'rgba(0, 0, 0, 0.1)',
                borderWidth: 2,
                hoverOffset: 8
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: chartColors.text,
                        font: { size: 12, weight: '600' },
                        padding: 15,
                        usePointStyle: true,
                        pointStyle: 'circle'
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: chartColors.text,
                    bodyColor: chartColors.text,
                    padding: 12,
                    displayColors: true,
                    borderColor: chartColors.primary,
                    borderWidth: 1,
                    callbacks: {
                        label: function (context) {
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = ((context.parsed / total) * 100).toFixed(1);
                            return context.label + ': ' + context.parsed + ' (' + percentage + '%)';
                        }
                    }
                }
            }
        }
    });
}

// Auto-refresh dashboard every 5 minutes
setInterval(loadDashboardData, 5 * 60 * 1000);
