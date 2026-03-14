GLASS_CSS = """
:root {
  --bg: #eaf2ff;
  --bg-subtle: #f8faff;
  --glass: rgba(255, 255, 255, 0.58);
  --glass-thick: rgba(255, 255, 255, 0.75);
  --border: rgba(255, 255, 255, 0.5);
  --text: #0b1220;
  --text-secondary: #56627a;
  --accent: #0a84ff;
  --accent-light: #6bd7ff;
  --danger: #ff3b30;
  --success: #34c759;
  --warning: #ff9500;
  --shadow: 0 24px 60px rgba(10, 20, 45, 0.22);
  --shadow-sm: 0 4px 12px rgba(10, 20, 45, 0.08);
  --blur: 26px;
  --radius: 16px;
  --radius-lg: 22px;
  --spacing: 1rem;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b1022;
    --bg-subtle: #111a2e;
    --glass: rgba(12, 18, 34, 0.62);
    --glass-thick: rgba(12, 18, 34, 0.82);
    --border: rgba(255, 255, 255, 0.14);
    --text: #ecf2ff;
    --text-secondary: #a7b6d3;
    --accent: #6bb7ff;
    --accent-light: #7ee1ff;
    --danger: #ff453a;
    --success: #30b140;
    --warning: #ff9f0a;
    --shadow: 0 26px 70px rgba(0, 0, 0, 0.45);
    --shadow-sm: 0 4px 12px rgba(0, 0, 0, 0.2);
  }
}

* { box-sizing: border-box; }

html, body {
  width: 100%;
  max-width: 100%;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", sans-serif;
  color: var(--text);
  background: linear-gradient(135deg, #eaf2ff 0%, #d4e4ff 100%);
  min-height: 100vh;
  overflow-x: hidden;
}

@media (prefers-color-scheme: dark) {
  body {
    background: linear-gradient(135deg, #0b1022 0%, #111a38 100%);
  }
}

/* Layout */
.navbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: linear-gradient(135deg, var(--glass), var(--glass));
  backdrop-filter: blur(var(--blur)) saturate(180%);
  -webkit-backdrop-filter: blur(var(--blur)) saturate(180%);
  border-bottom: 1px solid var(--border);
  padding: 1rem 2rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 2rem;
  flex-wrap: wrap;
  box-shadow: var(--shadow-sm);
}

.nav-brand h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.nav-status {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.nav-actions {
  display: flex;
  gap: 0.5rem;
}

.page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem 1rem 4rem;
  display: grid;
  gap: 2rem;
}

/* Cards & Surfaces */
.glass-surface {
  background: linear-gradient(135deg, var(--glass), rgba(255, 255, 255, 0.4));
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  backdrop-filter: blur(var(--blur)) saturate(180%);
  -webkit-backdrop-filter: blur(var(--blur)) saturate(180%);
  box-shadow: var(--shadow);
  position: relative;
  overflow: hidden;
}

.glass-surface::before {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.7), transparent);
  opacity: 0.5;
  pointer-events: none;
}

.glass-panel {
  background: linear-gradient(135deg, var(--glass-thick), rgba(255, 255, 255, 0.5));
  box-shadow: 0 8px 20px rgba(10, 20, 45, 0.08);
}

.glass-surface > *,
.glass-panel > * {
  position: relative;
  z-index: 1;
}

.card {
  padding: 2rem;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.card:hover {
  transform: translateY(-2px);
  box-shadow: 0 32px 80px rgba(10, 20, 45, 0.15);
}

/* Typography */
h1, h2, h3, h4 {
  margin: 0 0 0.5rem 0;
  font-weight: 600;
  letter-spacing: -0.01em;
}

h1 { font-size: 2rem; }
h2 { font-size: 1.5rem; }
h3 { font-size: 1.25rem; }
h4 { font-size: 1rem; }

.meta {
  font-size: 0.875rem;
  color: var(--text-secondary);
}

/* Sections */
.section-header {
  margin-bottom: 1.5rem;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 1rem;
}

.section-header h2 {
  margin: 0;
}

.link {
  color: var(--accent);
  text-decoration: none;
  font-weight: 600;
}

.link:hover {
  text-decoration: underline;
}

/* Forms */
.form {
  display: grid;
  gap: 1.5rem;
}

.field {
  display: grid;
  gap: 0.5rem;
}

.label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-secondary);
  font-weight: 600;
}

.input,
.textarea,
.select {
  width: 100%;
  padding: 0.75rem 1rem;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--glass-thick);
  color: var(--text);
  font-family: inherit;
  font-size: 1rem;
  transition: border-color 0.2s, box-shadow 0.2s;
  backdrop-filter: blur(12px) saturate(160%);
  -webkit-backdrop-filter: blur(12px) saturate(160%);
}

.input:focus,
.textarea:focus,
.select:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(10, 132, 255, 0.1);
}

.textarea {
  min-height: 100px;
  resize: vertical;
}

.input::placeholder {
  color: var(--text-secondary);
}

/* Buttons */
.btn {
  padding: 0.625rem 1rem;
  border-radius: 8px;
  border: 1px solid transparent;
  background: linear-gradient(135deg, rgba(255,255,255,0.8), rgba(255,255,255,0.4));
  color: var(--text);
  font-size: 0.9375rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(256, 256, 256, 0.3);
  border: 1px solid rgba(255,255,255,0.5);
}

.btn:hover:not(:disabled) {
  transform: scale(1.02);
  box-shadow: 0 6px 16px rgba(10, 20, 45, 0.15);
}

.btn:active:not(:disabled) {
  transform: scale(0.98);
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  pointer-events: none;
}

/* Button variants */
.btn.primary {
  background: linear-gradient(135deg, var(--accent-light), var(--accent));
  color: white;
  border-color: var(--accent);
  box-shadow: 0 8px 20px rgba(10, 132, 255, 0.3);
}

.btn.primary:hover:not(:disabled) {
  box-shadow: 0 12px 28px rgba(10, 132, 255, 0.4);
}

.btn.ghost {
  background: transparent;
  border: 1px solid var(--border);
  box-shadow: none;
}

.btn.danger {
  background: linear-gradient(135deg, rgba(255, 59, 48, 0.2), rgba(255, 59, 48, 0.1));
  color: var(--danger);
  border-color: rgba(255, 59, 48, 0.3);
}

.btn.danger:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(255, 59, 48, 0.3), rgba(255, 59, 48, 0.2));
}

/* Button groups */
.button-group {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.action-buttons {
  display: flex;
  gap: 0.5rem;
}

.blob-upload-zone {
  display: grid;
  gap: 0.5rem;
  margin-bottom: 1rem;
  padding: 1rem 1.25rem;
  border: 2px dashed rgba(10, 132, 255, 0.28);
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.15s ease, background 0.15s ease;
}

.blob-upload-zone:hover,
.blob-upload-zone.dragover {
  border-color: var(--accent);
  transform: translateY(-1px);
}

.blob-upload-zone[data-upload-state="uploading"] {
  border-color: var(--warning);
}

.blob-upload-zone[data-upload-state="error"] {
  border-color: var(--danger);
}

.blob-upload-zone[data-upload-state="done"] {
  border-color: var(--success);
}

.blob-upload-title {
  font-weight: 600;
}

/* Segmented controls */
.segmented {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
  gap: 0.75rem;
}

.seg-btn {
  padding: 0.625rem 1rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(255,255,255,0.7), rgba(255,255,255,0.3));
  color: var(--text-secondary);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 0.9375rem;
  text-align: center;
}

.seg-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(255,255,255,0.85), rgba(255,255,255,0.5));
}

.seg-btn.active {
  background: linear-gradient(135deg, var(--accent-light), var(--accent));
  color: white;
  border-color: var(--accent);
  box-shadow: 0 4px 12px rgba(10, 132, 255, 0.2);
}

.seg-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Stepper */
.stepper {
  display: flex;
  align-items: center;
  gap: 1rem;
  background: var(--glass-thick);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.75rem 1rem;
  width: fit-content;
}

.stepper-btn {
  width: 36px;
  height: 36px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(255,255,255,0.8), rgba(255,255,255,0.4));
  color: var(--text);
  font-size: 1.25rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
}

.stepper-btn:hover:not(:disabled) {
  transform: scale(1.08);
  background: linear-gradient(135deg, rgba(255,255,255,0.95), rgba(255,255,255,0.6));
}

.stepper-btn:active:not(:disabled) {
  transform: scale(0.94);
}

.stepper-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.stepper-value {
  min-width: 50px;
  text-align: center;
  font-weight: 600;
  color: var(--text);
}

/* Progress section */
.progress-section {
  background: linear-gradient(135deg, rgba(10,132,255,0.05), rgba(107,215,255,0.05));
  border-color: rgba(10,132,255,0.2);
}

.progress-display {
  display: grid;
  gap: 1.5rem;
  margin-bottom: 1.5rem;
}

.progress-metric {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.progress-metric .label {
  text-transform: none;
  font-size: 0.875rem;
  letter-spacing: normal;
}

.progress-metric .value {
  font-size: 2rem;
  font-weight: 700;
  color: var(--accent);
}

.progress-bar-container {
  height: 8px;
  background: rgba(0,0,0,0.1);
  border-radius: 4px;
  overflow: hidden;
  position: relative;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-light));
  border-radius: 4px;
  transition: width 0.3s ease;
}

.phase-selector {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.phase-btn {
  padding: 0.75rem 1rem;
  border-radius: 8px;
  border: 2px solid var(--border);
  background: linear-gradient(135deg, rgba(255,255,255,0.7), rgba(255,255,255,0.3));
  color: var(--text-secondary);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 0.875rem;
  text-align: center;
}

.phase-btn:hover:not(:disabled) {
  border-color: var(--accent);
  background: linear-gradient(135deg, rgba(255,255,255,0.85), rgba(255,255,255,0.5));
}

.phase-btn.active {
  border-color: var(--accent);
  background: linear-gradient(135deg, var(--accent-light), var(--accent));
  color: white;
  box-shadow: 0 4px 12px rgba(10, 132, 255, 0.3);
}

.phase-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Lists */
.list {
  display: grid;
  gap: 1rem;
}

.list-item {
  padding: 1.25rem;
  border-radius: 12px;
  display: grid;
  gap: 0.75rem;
  transition: all 0.2s ease;
}

.list-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 28px rgba(10, 20, 45, 0.12);
}

.item-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 1rem;
}

.item-header h4 {
  margin: 0;
}

.item-badges {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.item-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.task-item {
  border-left: 4px solid var(--accent);
}

/* Tables */
.table-wrap {
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9375rem;
}

.table th {
  padding: 1rem;
  text-align: left;
  font-weight: 600;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-secondary);
  background: rgba(255,255,255,0.6);
  border-bottom: 1px solid var(--border);
}

.table td {
  padding: 1rem;
  border-bottom: 1px solid rgba(0,0,0,0.05);
  color: var(--text);
}

.table tr:hover {
  background: rgba(255,255,255,0.05);
}

.table tr:last-child td {
  border-bottom: none;
}

/* Telemetry grid */
.telemetry-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.stat-box {
  padding: 1.25rem;
  border-radius: 12px;
  text-align: center;
  display: grid;
  gap: 0.5rem;
}

.stat-label {
  font-size: 0.875rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--accent);
}

/* Pills/Badges */
.pill {
  display: inline-flex;
  align-items: center;
  padding: 0.375rem 0.75rem;
  border-radius: 999px;
  font-size: 0.8125rem;
  font-weight: 600;
  border: 1px solid transparent;
  white-space: nowrap;
}

.pill-success { background: rgba(52, 199, 89, 0.12); color: var(--success); border-color: rgba(52, 199, 89, 0.3); }
.pill-danger { background: rgba(255, 59, 48, 0.12); color: var(--danger); border-color: rgba(255, 59, 48, 0.3); }
.pill-warning { background: rgba(255, 149, 0, 0.12); color: var(--warning); border-color: rgba(255, 149, 0, 0.3); }
.pill-info { background: rgba(10, 132, 255, 0.12); color: var(--accent); border-color: rgba(10, 132, 255, 0.3); }
.pill-muted { background: rgba(0, 0, 0, 0.05); color: var(--text-secondary); border-color: rgba(0, 0, 0, 0.08); }

.priority-high { background: rgba(255, 59, 48, 0.12); color: var(--danger); }
.priority-medium { background: rgba(255, 149, 0, 0.12); color: var(--warning); }
.priority-low { background: rgba(52, 199, 89, 0.12); color: var(--success); }

.status-done { background: rgba(52, 199, 89, 0.12); color: var(--success); }
.status-in-progress { background: rgba(255, 149, 0, 0.12); color: var(--warning); }

/* Modal */
.modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
  z-index: 1000;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.modal-card {
  width: min(600px, 90vw);
  max-height: 90vh;
  overflow-y: auto;
  padding: 2rem;
  display: grid;
  gap: 1.5rem;
  animation: slideUp 0.3s ease;
}

@keyframes slideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.modal-header {
  display: flex;
  justify-content: flex-end;
}

.modal-close {
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: 6px;
  font-size: 1.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-subtitle {
  margin: 0;
  font-size: 1.25rem;
}

.confirm-dialog {
  display: grid;
  gap: 1rem;
  padding: 1rem 0;
}

.confirm-dialog p {
  margin: 0;
  color: var(--text-secondary);
}

/* Form actions */
.form-actions {
  display: flex;
  gap: 0.75rem;
  justify-content: flex-end;
  flex-wrap: wrap;
  padding-top: 1rem;
  border-top: 1px solid var(--border);
}

/* Toast notification */
.toast {
  position: fixed;
  bottom: 2rem;
  right: 2rem;
  padding: 1rem 1.5rem;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  animation: slideInUp 0.3s ease;
  z-index: 999;
}

@keyframes slideInUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

/* Error state */
.error-state {
  display: grid;
  gap: 1rem;
  text-align: center;
}

/* Utilities */
.glass-input {
  background: var(--glass);
}

/* Dark mode adjustments */
@media (prefers-color-scheme: dark) {
  .table th {
    background: rgba(255,255,255,0.08);
  }

  .seg-btn {
    background: linear-gradient(135deg, rgba(30, 43, 75, 0.8), rgba(20, 30, 56, 0.6));
    color: var(--text-secondary);
    border-color: rgba(150, 185, 255, 0.2);
  }

  .seg-btn.active {
    background: linear-gradient(135deg, var(--accent-light), var(--accent));
    color: white;
  }

  .btn {
    background: linear-gradient(135deg, rgba(30, 43, 75, 0.8), rgba(20, 30, 56, 0.6));
    color: var(--text);
  }

  .input, .textarea, .select {
    background: rgba(30, 43, 75, 0.7);
    border-color: rgba(150, 185, 255, 0.2);
    color: var(--text);
  }

  .pill-success { background: rgba(52, 199, 89, 0.15); }
  .pill-danger { background: rgba(255, 59, 48, 0.15); }
  .pill-warning { background: rgba(255, 149, 0, 0.15); }
  .pill-info { background: rgba(10, 132, 255, 0.15); }
}

/* Responsive */
@media (max-width: 768px) {
  .navbar {
    padding: 1rem;
    flex-direction: column;
    align-items: flex-start;
  }

  .nav-status, .nav-actions {
    width: 100%;
  }

  .page {
    padding: 1rem;
    gap: 1rem;
  }

  .card {
    padding: 1.5rem;
  }

  .section-header {
    flex-direction: column;
  }

  .phase-selector {
    grid-template-columns: repeat(auto-fit, minmax(60px, 1fr));
  }

  .modal-card {
    padding: 1.5rem;
  }

  .table {
    font-size: 0.875rem;
  }

  .table th, .table td {
    padding: 0.75rem;
  }

  .toast {
    bottom: 1rem;
    right: 1rem;
    left: 1rem;
  }
}
"""
