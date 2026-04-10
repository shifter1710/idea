from __future__ import annotations

import html


INLINE_SCRIPT = """
<script>
document.addEventListener('DOMContentLoaded', function () {
  const input = document.getElementById('scale-search');
  if (!input) return;
  const cards = Array.from(document.querySelectorAll('.scale-card[data-search]'));
  input.addEventListener('input', function () {
    const q = input.value.trim().toLowerCase();
    cards.forEach(function (card) {
      const hit = !q || (card.dataset.search || '').includes(q);
      card.style.display = hit ? '' : 'none';
    });
  });
});
</script>
"""


INLINE_STYLES = """
:root {
  --bg: #efe6d8;
  --panel: rgba(255, 250, 242, 0.92);
  --panel-strong: #fffdf8;
  --ink: #1d1b19;
  --accent: #9d3c27;
  --accent-soft: #d58d62;
  --accent-deep: #6e2417;
  --line: #dccfbf;
  --line-strong: #ceb79f;
  --muted: #5a544d;
  --danger: #a43228;
  --danger-soft: #fde9e5;
  --shadow: 0 18px 44px rgba(67, 45, 29, .10);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
  background:
    radial-gradient(circle at top left, #fff8ec 0, rgba(255,248,236,.7) 28%, transparent 52%),
    radial-gradient(circle at bottom right, rgba(213,141,98,.18), transparent 32%),
    linear-gradient(180deg, #e9dcc8, #f5efe5 42%, #efe7dc);
  color: var(--ink);
}
a { color: var(--accent); text-decoration: none; }
.shell { max-width: 1200px; margin: 0 auto; padding: 24px; }
.topbar {
  display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between;
  position: sticky; top: 0; z-index: 10;
  padding: 14px 0 18px;
  border-bottom: 1px solid rgba(206, 183, 159, .65);
  margin-bottom: 24px;
  backdrop-filter: blur(10px);
  background: linear-gradient(180deg, rgba(245,239,229,.92), rgba(245,239,229,.62));
}
.brand { font-size: 28px; font-weight: 700; letter-spacing: .03em; }
.nav { display: flex; flex-wrap: wrap; gap: 14px; }
.nav a {
  padding: 10px 14px;
  border-radius: 999px;
  color: var(--ink);
  background: rgba(255,255,255,.42);
  border: 1px solid rgba(206,183,159,.5);
}
.hero, .page-head, .result-card, .scale-card, .stack-form, table {
  background: var(--panel);
  border: 1px solid rgba(220, 207, 191, .95);
  border-radius: 22px;
  box-shadow: var(--shadow);
  overflow: hidden;
  background-clip: padding-box;
}
.hero, .page-head, .result-card, .stack-form { padding: 24px; margin-bottom: 24px; }
.page-head.compact { padding: 18px 24px; }
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(280px, .7fr);
  gap: 22px;
  align-items: stretch;
  background:
    linear-gradient(135deg, rgba(255,251,245,.97), rgba(248,239,227,.88)),
    radial-gradient(circle at top right, rgba(157,60,39,.12), transparent 40%);
}
.hero-copy { display: grid; gap: 18px; }
.hero-panel {
  display: grid;
  gap: 16px;
  align-content: space-between;
  background: linear-gradient(180deg, rgba(250,242,230,.86), rgba(255,255,255,.7));
  border: 1px solid rgba(206,183,159,.75);
  border-radius: 18px;
  padding: 20px;
  overflow: hidden;
}
.hero h1, .page-head h1 { margin: 0 0 8px; font-size: 44px; line-height: .98; letter-spacing: -.02em; }
.page-head h2, .result-card h2 { margin: 0 0 8px; font-size: 28px; }
.hero p, .page-head p, .meta { color: var(--muted); }
.button {
  display: inline-block; border: 0; border-radius: 999px; background: linear-gradient(180deg, var(--accent), var(--accent-deep)); color: #fff;
  padding: 12px 18px; cursor: pointer; font: inherit;
  box-shadow: 0 12px 24px rgba(110, 36, 23, .18);
}
.button.secondary {
  background: linear-gradient(180deg, #f4e8d9, #ead6bf);
  color: var(--ink);
  box-shadow: none;
  border: 1px solid rgba(206,183,159,.8);
}
.button.active {
  background: linear-gradient(180deg, var(--accent), var(--accent-deep));
  box-shadow: inset 0 0 0 2px rgba(255,255,255,.25), 0 12px 24px rgba(110, 36, 23, .18);
}
.hero-links { display: flex; flex-wrap: wrap; gap: 10px; }
.tag-row, .duel-summary { display: flex; flex-wrap: wrap; gap: 12px; }
.info-tag, .duel-pill {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  min-width: 110px;
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(255,255,255,.6);
  border: 1px solid rgba(206,183,159,.7);
  overflow: hidden;
  color: var(--muted);
}
.info-tag { min-width: auto; flex-direction: row; align-items: center; }
.duel-pill strong { font-size: 28px; line-height: 1; color: var(--ink); }
.duel-pill.accent {
  background: linear-gradient(180deg, rgba(157,60,39,.12), rgba(213,141,98,.18));
  border-color: rgba(157,60,39,.25);
}
.calc-switches { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }
.switch-panel {
  padding: 10px;
  border-radius: 20px;
  background: rgba(255,250,242,.68);
  border: 1px solid rgba(220,207,191,.85);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
.scale-card {
  padding: 18px;
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
  background: linear-gradient(180deg, rgba(255,253,248,.92), rgba(252,245,235,.88));
}
.scale-card:hover {
  transform: translateY(-3px);
  border-color: rgba(157,60,39,.3);
  box-shadow: 0 22px 38px rgba(67, 45, 29, .12);
}
.stack-form { display: grid; gap: 14px; }
.compact-form { grid-template-columns: minmax(0, 1fr) auto; align-items: end; }
.calc-row, .compare-row, .compare-tables, .combined-row { display: grid; gap: 14px; }
.calc-row { grid-template-columns: minmax(0, 1.3fr) minmax(180px, .8fr) auto; }
.combined-row {
  grid-template-columns: minmax(180px, .8fr) minmax(180px, 1fr) auto;
  align-items: end;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255,253,248,.94), rgba(249,241,230,.86));
}
.compare-row, .compare-tables { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.compare-col {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(255,253,248,.94), rgba(249,241,230,.86));
  overflow: hidden;
}
.check-stack {
  display: grid;
  gap: 8px;
  align-self: end;
  padding-bottom: 10px;
}
label { display: grid; gap: 8px; font-weight: 700; }
.inline-check { display: flex; align-items: center; gap: 10px; font-weight: 400; }
.compact-check { align-self: end; padding-bottom: 12px; }
input, select {
  width: 100%; padding: 12px 14px; border: 1px solid var(--line-strong); border-radius: 14px;
  background: var(--panel-strong); font: inherit; color: var(--ink);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.75);
}
input[type='checkbox'] { width: auto; }
input:focus, select:focus {
  outline: 2px solid rgba(157,60,39,.22);
  border-color: rgba(157,60,39,.55);
}
.search-panel, .calculator-head, .scale-head {
  background: linear-gradient(180deg, rgba(255,251,245,.96), rgba(247,238,226,.88));
}
.field-error {
  margin: -2px 0 0;
  color: var(--danger);
  font-size: 14px;
}
.form-alert {
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(164, 50, 40, .25);
  background: var(--danger-soft);
  color: var(--danger);
}
.score-hero {
  display: grid;
  grid-template-columns: minmax(180px, .45fr) minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
.score-value {
  display: grid;
  align-content: center;
  gap: 6px;
  min-height: 160px;
  border-radius: 22px;
  background: linear-gradient(180deg, rgba(157,60,39,.96), rgba(110,36,23,.96));
  color: #fff;
  padding: 22px;
  font-size: 54px;
  line-height: .9;
  text-align: center;
  box-shadow: 0 20px 40px rgba(110,36,23,.22);
  overflow: hidden;
}
.score-value.solo { margin-bottom: 20px; min-height: 0; font-size: 46px; }
.score-value small {
  font-size: 16px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: rgba(255,255,255,.78);
}
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  overflow: hidden;
}
th, td { padding: 12px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th {
  background: linear-gradient(180deg, #f1e3d0, #ead6bf);
  font-size: 14px;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: var(--muted);
}
thead th:first-child { border-top-left-radius: 18px; }
thead th:last-child { border-top-right-radius: 18px; }
tbody tr:last-child td:first-child { border-bottom-left-radius: 18px; }
tbody tr:last-child td:last-child { border-bottom-right-radius: 18px; }
tbody tr:last-child td { border-bottom: 0; }
@media (max-width: 900px) {
  .hero, .score-hero, .compact-form, .calc-row, .compare-row, .compare-tables, .combined-row { grid-template-columns: 1fr; }
  .hero h1, .page-head h1 { font-size: 32px; }
  .score-value { min-height: 0; font-size: 42px; }
  .shell { padding: 16px; }
}
"""


def render_layout(title: str, body: str) -> str:
    navigation = (
        "<header class='topbar'>"
        "<div class='brand'>Очки WA 2025</div>"
        "<nav class='nav'>"
        "<a href='/'>Главная</a>"
        "<a href='/calculate'>Калькулятор</a>"
        "</nav>"
        "</header>"
    )
    return (
        "<!doctype html><html lang='ru'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title>"
        f"<style>{INLINE_STYLES}</style>"
        f"{INLINE_SCRIPT}</head><body><div class='shell'>"
        f"{navigation}{body}"
        "</div></body></html>"
    )


def render_field_error(message: str) -> str:
    if not message:
        return ""
    return f"<p class='field-error'>{html.escape(message)}</p>"


def render_form_alert(message: str | None) -> str:
    if not message:
        return ""
    return f"<div class='form-alert'>{html.escape(message)}</div>"


def render_datalist(labels: list[str], datalist_id: str) -> str:
    options = "".join(f"<option value='{html.escape(label)}'></option>" for label in labels)
    return f"<datalist id='{html.escape(datalist_id)}'>{options}</datalist>"
