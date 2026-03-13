GLASS_CSS = """
:root {
  color-scheme: light;
  --bg: #eaf2ff;
  --bg-2: #86c9ff;
  --bg-3: #356eff;
  --bg-4: #f2f6ff;
  --glass: rgba(255, 255, 255, 0.58);
  --glass-2: rgba(255, 255, 255, 0.32);
  --border: rgba(255, 255, 255, 0.5);
  --text: #0b1220;
  --muted: #56627a;
  --shadow: 0 24px 60px rgba(10, 20, 45, 0.22);
  --shadow-soft: 0 12px 30px rgba(10, 20, 45, 0.14);
  --blur: 26px;
  --radius: 22px;
  --accent: #0a84ff;
  --accent-2: #6bd7ff;
  --accent-3: #ff7ad9;
  --glow-1: rgba(255, 255, 255, 0.9);
  --glow-2: rgba(110, 200, 255, 0.5);
  --glow-3: rgba(255, 120, 215, 0.4);
  --vignette: rgba(10, 16, 30, 0.25);
}

@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #0b1022;
    --bg-2: #111f3d;
    --bg-3: #1b2f61;
    --bg-4: #0b142b;
    --glass: rgba(12, 18, 34, 0.62);
    --glass-2: rgba(12, 18, 34, 0.42);
    --border: rgba(255, 255, 255, 0.14);
    --text: #ecf2ff;
    --muted: #a7b6d3;
    --shadow: 0 26px 70px rgba(0, 0, 0, 0.45);
    --shadow-soft: 0 12px 32px rgba(0, 0, 0, 0.3);
    --blur: 30px;
    --accent: #6bb7ff;
    --accent-2: #7ee1ff;
    --accent-3: #ff8bde;
    --glow-1: rgba(120, 160, 255, 0.35);
    --glow-2: rgba(80, 150, 255, 0.4);
    --glow-3: rgba(255, 130, 220, 0.3);
    --vignette: rgba(0, 0, 0, 0.5);
  }
}

* { box-sizing: border-box; }

html, body {
  width: 100%;
  max-width: 100%;
}

body {
  margin: 0;
  font-family: "SF Pro Text", "SF Pro Display", "Helvetica Neue", "Segoe UI", sans-serif;
  color: var(--text);
  background:
    radial-gradient(1200px 700px at 10% -10%, var(--glow-1), transparent 60%),
    radial-gradient(900px 700px at 110% 0%, var(--glow-3), transparent 65%),
    radial-gradient(800px 600px at -10% 60%, var(--glow-2), transparent 70%),
    radial-gradient(120% 120% at 50% 30%, rgba(255, 255, 255, 0.18), var(--vignette) 70%),
    linear-gradient(155deg, var(--bg-2) 0%, var(--bg-3) 55%, var(--bg-4) 100%);
  min-height: 100vh;
  overflow-x: hidden;
  position: relative;
  isolation: isolate;
}

body::before {
  content: "";
  position: fixed;
  inset: -20% -10% auto -10%;
  height: 70vh;
  background:
    radial-gradient(600px 320px at 15% 15%, rgba(255, 255, 255, 0.6), transparent 70%),
    radial-gradient(700px 340px at 70% 0%, rgba(255, 255, 255, 0.35), transparent 72%);
  filter: blur(44px) saturate(160%);
  pointer-events: none;
  z-index: -1;
}

body::after {
  content: "";
  position: fixed;
  inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='120' height='120' filter='url(%23n)' opacity='0.4'/%3E%3C/svg%3E");
  opacity: 0.07;
  mix-blend-mode: soft-light;
  pointer-events: none;
  z-index: 3;
}

.page {
  max-width: 1120px;
  margin: 0 auto;
  padding: 32px 24px 88px;
  display: grid;
  gap: 24px;
  position: relative;
  z-index: 1;
}

.glass-surface {
  background: linear-gradient(135deg, var(--glass), var(--glass-2));
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow:
    var(--shadow),
    inset 0 1px 0 rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(var(--surface-blur, var(--blur))) saturate(180%);
  -webkit-backdrop-filter: blur(var(--surface-blur, var(--blur))) saturate(180%);
  position: relative;
  overflow: hidden;
}

.glass-surface::before {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.7), rgba(255, 255, 255, 0));
  opacity: 0.55;
  pointer-events: none;
}

.glass-surface::after {
  content: "";
  position: absolute;
  inset: auto -20% -45% -20%;
  height: 70%;
  background:
    radial-gradient(320px 220px at 15% 20%, rgba(10, 132, 255, 0.35), transparent 70%),
    radial-gradient(320px 220px at 85% 80%, rgba(255, 122, 217, 0.32), transparent 70%);
  opacity: 0.55;
  mix-blend-mode: screen;
  pointer-events: none;
}

.glass-surface > * { position: relative; z-index: 1; }

.glass-card { --surface-blur: calc(var(--blur) + 6px); }
.glass-panel { --surface-blur: calc(var(--blur) - 4px); }

.card {
  padding: 24px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
}

.navbar {
  max-width: 1120px;
  margin: 20px auto 0;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  position: sticky;
  top: 16px;
  z-index: 10;
}

.glass-navbar { --surface-blur: calc(var(--blur) + 10px); }

.nav-left {
  display: grid;
  gap: 2px;
  min-width: 0;
  flex: 1 1 280px;
}

.nav-eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.28em;
  font-size: 10px;
  color: var(--muted);
}

.nav-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.01em;
  overflow-wrap: anywhere;
}

.nav-meta {
  font-size: 12px;
  color: var(--muted);
  overflow-wrap: anywhere;
}

.nav-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.3em;
  font-size: 11px;
  color: var(--muted);
}

h1, h2 {
  margin: 0 0 8px;
  font-weight: 600;
  letter-spacing: -0.02em;
}

h1 { font-size: 32px; }

h2 { font-size: 20px; margin-bottom: 4px; }

.meta { color: var(--muted); font-size: 14px; }

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.doc-filter {
  display: grid;
  gap: 10px;
  margin-bottom: 16px;
}

.doc-filter .segmented {
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
}

.glass-btn,
.btn {
  border: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.8), rgba(255, 255, 255, 0.35));
  padding: 10px 16px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text);
  box-shadow:
    var(--shadow-soft),
    inset 0 1px 0 rgba(255, 255, 255, 0.6);
  position: relative;
  overflow: hidden;
  backdrop-filter: blur(14px) saturate(160%);
  -webkit-backdrop-filter: blur(14px) saturate(160%);
  transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}

.glass-btn::before,
.btn::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0) 55%),
    radial-gradient(80px 40px at 20% 0%, rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0));
  opacity: 0.75;
  pointer-events: none;
}

.btn.primary {
  background: linear-gradient(160deg, var(--accent-2), var(--accent) 55%, #0a4bd6 100%);
  color: #fff;
  border: 1px solid rgba(10, 120, 255, 0.55);
  box-shadow:
    0 18px 44px rgba(10, 130, 255, 0.35),
    inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.btn.secondary {
  background: linear-gradient(160deg, rgba(255, 255, 255, 0.7), rgba(255, 255, 255, 0.3));
  color: var(--text);
}

.btn.primary::before { opacity: 0.35; }

.btn.ghost {
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.5);
  box-shadow: none;
}

.btn:focus-visible,
.seg-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 4px rgba(10, 132, 255, 0.2);
}

.btn[disabled],
.glass-btn[disabled],
.seg-btn[disabled] {
  cursor: wait;
  opacity: 0.6;
  pointer-events: none;
  transform: none !important;
  box-shadow: none !important;
}

.input[disabled],
.textarea[disabled] {
  opacity: 0.75;
  cursor: not-allowed;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0.55));
  font-size: 12px;
  color: var(--muted);
}

.pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid transparent;
}

.pill-success { background: rgba(68, 201, 140, 0.18); color: #0f5132; border-color: rgba(68, 201, 140, 0.5); }
.pill-warning { background: rgba(255, 176, 86, 0.2); color: #7a4b0b; border-color: rgba(255, 176, 86, 0.5); }
.pill-danger { background: rgba(255, 99, 99, 0.2); color: #7a1010; border-color: rgba(255, 99, 99, 0.5); }
.pill-info { background: rgba(86, 160, 255, 0.2); color: #133d7a; border-color: rgba(86, 160, 255, 0.5); }
.pill-muted { background: rgba(15, 23, 42, 0.08); color: var(--muted); border-color: rgba(15, 23, 42, 0.12); }

.progress-card {
  padding: 16px;
  display: grid;
  gap: 12px;
  border-radius: 18px;
}

.progress-track {
  height: 12px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 999px;
  overflow: hidden;
  position: relative;
}

.progress-track span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
}

.phase-track {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}

.phase-step {
  text-align: center;
  font-size: 11px;
  padding: 6px 4px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.65);
  color: var(--muted);
  border: 1px solid rgba(255, 255, 255, 0.5);
  cursor: pointer;
  font-family: inherit;
  appearance: none;
}

.phase-step.active {
  background: rgba(10, 132, 255, 0.15);
  color: var(--accent);
  border-color: rgba(10, 132, 255, 0.5);
  font-weight: 600;
}

.list { display: grid; gap: 12px; }

.log-entry,
.task-row {
  padding: 14px 16px;
  border-radius: 16px;
  display: grid;
  gap: 8px;
}

.task-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.task-meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }

.table-wrap {
  border-radius: 16px;
  overflow-x: auto;
}

.table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.table th, .table td {
  text-align: left;
  padding: 12px 12px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}

.table th {
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.6);
}

.table tr:last-child td { border-bottom: none; }

.link { color: var(--accent); text-decoration: none; font-weight: 600; }
.link:hover { text-decoration: underline; }

.modal {
  position: fixed;
  inset: 0;
  background: rgba(8, 16, 32, 0.45);
  backdrop-filter: blur(16px) saturate(160%);
  -webkit-backdrop-filter: blur(16px) saturate(160%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 40;
}

.modal-card {
  width: min(720px, 95vw);
  padding: 24px;
  display: grid;
  gap: 16px;
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-title { font-size: 20px; margin: 0; }

.form { display: grid; gap: 14px; }

.field { display: grid; gap: 6px; }

.label {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
}

.helper { font-size: 12px; color: var(--muted); }

.glass-input,
.input, .textarea, .select {
  width: 100%;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.4);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0.5));
  font-size: 14px;
  color: var(--text);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(12px) saturate(160%);
  -webkit-backdrop-filter: blur(12px) saturate(160%);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.input:focus, .textarea:focus, .select:focus {
  outline: none;
  border-color: rgba(10, 132, 255, 0.6);
  box-shadow: 0 0 0 4px rgba(10, 132, 255, 0.2);
}

.textarea { min-height: 120px; resize: vertical; }

.segmented {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px;
}

.seg-btn {
  padding: 10px 12px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.82), rgba(255, 255, 255, 0.45));
  color: var(--muted);
  cursor: pointer;
  font-weight: 600;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.seg-btn.active {
  background: rgba(10, 132, 255, 0.18);
  border-color: rgba(10, 132, 255, 0.5);
  color: var(--accent);
  box-shadow: var(--shadow-soft);
}

.form-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

@supports not ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))) {
  .glass-surface,
  .glass-btn,
  .glass-input,
  .glass-navbar {
    background: rgba(255, 255, 255, 0.92);
  }
}

@media (prefers-color-scheme: dark) {
  .glass-surface {
    border-color: rgba(158, 190, 255, 0.24);
    box-shadow:
      var(--shadow),
      inset 0 1px 0 rgba(255, 255, 255, 0.09);
  }

  .glass-surface::before {
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.14), rgba(255, 255, 255, 0));
    opacity: 0.7;
  }

  .glass-btn,
  .btn,
  .btn.secondary {
    background: linear-gradient(135deg, rgba(32, 47, 82, 0.84), rgba(20, 30, 56, 0.72));
    color: var(--text);
    border-color: rgba(150, 185, 255, 0.28);
    box-shadow:
      0 12px 30px rgba(0, 0, 0, 0.35),
      inset 0 1px 0 rgba(255, 255, 255, 0.1);
  }

  .glass-btn::before,
  .btn::before {
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.16), rgba(255, 255, 255, 0) 58%),
      radial-gradient(80px 40px at 20% 0%, rgba(190, 225, 255, 0.24), rgba(255, 255, 255, 0));
    opacity: 0.7;
  }

  .btn.primary {
    color: #eaf5ff;
    border-color: rgba(98, 180, 255, 0.6);
    box-shadow:
      0 16px 40px rgba(20, 120, 255, 0.35),
      inset 0 1px 0 rgba(255, 255, 255, 0.22);
  }

  .btn.ghost {
    background: rgba(120, 150, 220, 0.16);
    border-color: rgba(160, 190, 255, 0.34);
  }

  .tag {
    background: linear-gradient(135deg, rgba(36, 50, 85, 0.82), rgba(26, 36, 64, 0.68));
    color: #cad7f2;
    border-color: rgba(150, 185, 255, 0.25);
  }

  .pill-success { background: rgba(48, 196, 135, 0.22); color: #9af4c8; border-color: rgba(75, 218, 154, 0.44); }
  .pill-warning { background: rgba(255, 176, 86, 0.22); color: #ffd69f; border-color: rgba(255, 196, 126, 0.42); }
  .pill-danger { background: rgba(255, 99, 99, 0.24); color: #ffc0c0; border-color: rgba(255, 131, 131, 0.42); }
  .pill-info { background: rgba(86, 160, 255, 0.23); color: #b9d8ff; border-color: rgba(126, 184, 255, 0.42); }
  .pill-muted { background: rgba(159, 182, 230, 0.14); color: #c4d1eb; border-color: rgba(174, 197, 245, 0.26); }

  .progress-track { background: rgba(150, 180, 230, 0.22); }

  .phase-step {
    background: rgba(32, 46, 80, 0.8);
    color: #c5d4f1;
    border-color: rgba(158, 190, 255, 0.3);
  }

  .table th,
  .table td {
    border-bottom-color: rgba(170, 195, 240, 0.16);
  }

  .table th {
    background: rgba(26, 37, 65, 0.75);
    color: #c7d6f2;
  }

  .glass-input,
  .input, .textarea, .select {
    border-color: rgba(150, 185, 255, 0.3);
    background: linear-gradient(135deg, rgba(30, 43, 75, 0.84), rgba(20, 30, 56, 0.68));
    color: #edf4ff;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1);
  }

  .input::placeholder,
  .textarea::placeholder {
    color: rgba(201, 216, 245, 0.65);
  }

  .seg-btn {
    background: linear-gradient(135deg, rgba(34, 48, 82, 0.84), rgba(22, 33, 60, 0.66));
    color: #c6d4ef;
    border-color: rgba(150, 185, 255, 0.28);
  }

  .seg-btn.active {
    background: rgba(91, 167, 255, 0.24);
    border-color: rgba(114, 185, 255, 0.58);
    color: #def0ff;
  }

  .link { color: #9dcbff; }
  .modal { background: rgba(4, 9, 20, 0.62); }

  @supports not ((-webkit-backdrop-filter: blur(1px)) or (backdrop-filter: blur(1px))) {
    .glass-surface,
    .glass-btn,
    .glass-input,
    .glass-navbar {
      background: rgba(12, 18, 34, 0.92);
    }
  }
}

@media (hover: hover) and (pointer: fine) {
  .card:hover,
  .glass-panel:hover,
  .glass-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 30px 70px rgba(10, 20, 45, 0.28);
  }

  .btn:hover,
  .seg-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 18px 36px rgba(10, 20, 45, 0.22);
  }
}

@media (max-width: 720px) {
  h1 { font-size: 26px; }
  .page { padding: 24px 16px 70px; }
  .card { padding: 16px; }
  .section-head { align-items: flex-start; }
  .navbar {
    margin: 16px 16px 0;
    padding: 12px 14px;
    top: 8px;
  }
  .nav-left { flex-basis: 100%; }
  .nav-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .task-row { align-items: flex-start; }
  .task-row > :last-child {
    width: 100%;
    justify-content: flex-start;
  }
  .phase-track { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .modal { padding: 12px; }
  .modal-card {
    width: min(720px, calc(100vw - 24px));
    padding: 16px;
  }
  .modal-head {
    flex-wrap: wrap;
    gap: 8px;
    align-items: flex-start;
  }
  .form-actions { justify-content: flex-start; }
}

@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }

  .card,
  .glass-panel,
  .glass-card,
  .btn,
  .seg-btn { transform: none !important; }
}
"""
