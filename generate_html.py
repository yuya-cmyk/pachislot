"""
HTML生成（日次・統計）
"""
import html as html_lib
from datetime import date, timedelta
from pathlib import Path

from database import get_connection

REPORT_DIR  = Path(__file__).parent / "reports"
ARCHIVE_DIR = REPORT_DIR / "archive"

CSS = r"""
body{font-family:"Hiragino Sans","Meiryo",sans-serif;background:#f0f2f5;margin:0;padding:16px;color:#1a1a2e}
.container{max-width:1400px;margin:0 auto}
h1{font-size:1.2em;color:#1a1a2e;border-bottom:3px solid #4a6fa5;padding-bottom:8px;margin-bottom:4px}
.sub{font-size:.8em;color:#666;margin-bottom:16px}
.nav{margin-bottom:16px;font-size:.85em}
.nav a{color:#4a6fa5;text-decoration:none;margin-right:16px}
.nav a:hover{text-decoration:underline}
.card{background:#fff;border-radius:8px;padding:16px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.1)}
.card h2{font-size:.95em;color:#4a6fa5;margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid #e0e8f4}
.tag{display:inline-block;font-size:.68em;padding:1px 5px;border-radius:3px;margin-left:4px;font-weight:bold;vertical-align:middle}
.tag-s20{background:#e8f4fd;color:#1565c0}
.tag-s5{background:#fce8f3;color:#880e4f}
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:.8em}
th{background:#4a6fa5;color:#fff;padding:6px 8px;text-align:right;white-space:nowrap;cursor:pointer;user-select:none}
th.L{text-align:left}
th.asc::after{content:" ▲"}
th.desc::after{content:" ▼"}
td{padding:5px 8px;border-bottom:1px solid #f0f0f0;text-align:right;white-space:nowrap}
td.L{text-align:left}
tr:hover td{background:#f5f8ff}
.pos{color:#c0392b;font-weight:bold}
.neg{color:#1565c0;font-weight:bold}
.zero{color:#888}
.summary{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
.stat-box{background:#fff;border-radius:8px;padding:10px 18px;box-shadow:0 1px 4px rgba(0,0,0,.1);text-align:center;min-width:110px}
.stat-box .val{font-size:1.3em;font-weight:bold}
.stat-box .lbl{font-size:.72em;color:#888;margin-top:3px}
.filter-bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-bottom:10px;padding:10px 12px;background:#f8f9ff;border-radius:6px;border:1px solid #e0e8f4}
#filter-name{flex:1;min-width:180px;padding:6px 10px;border:1px solid #ccc;border-radius:4px;font-size:.88em}
.denom-filter{display:flex;gap:12px;align-items:center}
.denom-filter label{font-size:.84em;cursor:pointer;white-space:nowrap}
#filter-count{font-size:.78em;color:#888;margin-left:auto}
.footer{font-size:.7em;color:#aaa;text-align:center;margin-top:24px;padding-top:12px;border-top:1px solid #e0e0e0}
@media(max-width:700px){
  .summary{flex-direction:column}
  .stat-box{min-width:0}
  th,td{padding:4px 5px;font-size:.75em}
}
"""

JS = r"""
<script>
(function(){
  // ── ソート ──────────────────────────────────────────────────
  function sortTable(tbl, col, asc) {
    var tbody = tbl.querySelector('tbody');
    var all = Array.from(tbody.querySelectorAll('tr'));
    all.sort(function(a, b) {
      var av = a.cells[col].getAttribute('data-v') || a.cells[col].textContent.trim();
      var bv = b.cells[col].getAttribute('data-v') || b.cells[col].textContent.trim();
      var an = parseFloat(av.replace(/,/g,'').replace(/\+/g,'')),
          bn = parseFloat(bv.replace(/,/g,'').replace(/\+/g,''));
      if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
      return asc ? av.localeCompare(bv, 'ja') : bv.localeCompare(av, 'ja');
    });
    all.forEach(function(r){ tbody.appendChild(r); });
  }
  function initSort(tbl, defCol, defAsc) {
    var state = {};
    tbl.querySelectorAll('th').forEach(function(th, i){
      th.addEventListener('click', function(){
        tbl.querySelectorAll('th').forEach(function(t){ t.classList.remove('asc','desc'); });
        if (state[i] === undefined) state[i] = (i === defCol) ? defAsc : true;
        else state[i] = !state[i];
        th.classList.add(state[i] ? 'asc' : 'desc');
        sortTable(tbl, i, state[i]);
      });
    });
    var ths = tbl.querySelectorAll('th');
    if (ths[defCol]) {
      ths[defCol].classList.add(defAsc ? 'asc' : 'desc');
      sortTable(tbl, defCol, defAsc);
    }
  }
  document.querySelectorAll('table.sortable').forEach(function(tbl){
    var defCol = parseInt(tbl.getAttribute('data-default-col') || '0');
    var defAsc = (tbl.getAttribute('data-default-asc') || 'true') === 'true';
    initSort(tbl, defCol, defAsc);
  });

  // ── 絞り込み ──────────────────────────────────────────────
  var nameInput = document.getElementById('filter-name');
  if (nameInput) {
    function applyFilter() {
      var name = nameInput.value.toLowerCase();
      var denomEl = document.querySelector('input[name="fd"]:checked');
      var denom = denomEl ? denomEl.value : 'all';
      var count = 0;
      document.querySelectorAll('.filterable tbody tr').forEach(function(row) {
        var nm = (row.getAttribute('data-name') || '').toLowerCase();
        var dn = row.getAttribute('data-denom') || '';
        var ok = nm.includes(name) && (denom === 'all' || dn === denom);
        row.style.display = ok ? '' : 'none';
        if (ok) count++;
      });
      var el = document.getElementById('filter-count');
      if (el) el.textContent = count + '台表示中';
    }
    nameInput.addEventListener('input', applyFilter);
    document.querySelectorAll('input[name="fd"]').forEach(function(r){
      r.addEventListener('change', applyFilter);
    });
  }
})();
</script>
"""


# ── フォーマット関数 ──────────────────────────────────────────────────────────

def _sign_cls(v):
    if v is None or v == 0:
        return "zero"
    return "pos" if v > 0 else "neg"

def _diff_approx_fmt(v):
    if v is None:
        return "---"
    sign = "+" if v >= 0 else ""
    return f"約{sign}{v:,}枚"

def _sign(v):
    if v is None:
        return "---"
    return f"+{v:,}" if v > 0 else f"{v:,}"

def _fmt(v, digits=0):
    if v is None:
        return "---"
    if digits:
        return f"{v:,.{digits}f}"
    return f"{v:,}"

def _prob(v):
    if v is None:
        return "---"
    return f"1/{v:.0f}"

def _td(val, fmt="", cls=""):
    txt = fmt if fmt else (str(val) if val is not None else "---")
    dv = f' data-v="{val}"' if val is not None else ' data-v="-99999999"'
    c = f' class="{cls}"' if cls else ''
    return f"<td{dv}{c}>{html_lib.escape(txt)}</td>"

def _th(label, cls=""):
    c = f' class="{cls}"' if cls else ''
    return f"<th{c}>{label}</th>"


# ── 日次HTML ──────────────────────────────────────────────────────────────────

def generate_daily_html(target_date: str) -> Path:
    conn = get_connection()
    rows = conn.execute("""
        SELECT machine_no, machine_name, denom,
               coin_diff, bb_count, rb_count, art_count,
               bb_prob, syn_prob, total_start, art_games, final_start,
               diff_approx, first_start
        FROM daily_records
        WHERE date = ?
        ORDER BY machine_no
    """, (target_date,)).fetchall()
    conn.close()

    # デノミ別台数
    model_count = {}
    for r in rows:
        key = (r["machine_name"], r["denom"])
        model_count[key] = model_count.get(key, 0) + 1

    d = target_date
    date_disp = f"{d[:4]}/{d[4:6]}/{d[6:]}"
    weekdays = "月火水木金土日"
    try:
        wd = weekdays[date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday()]
    except Exception:
        wd = ""

    # サマリ集計
    total  = len(rows)
    played = sum(1 for r in rows if r["total_start"] and r["total_start"] > 0)
    has_diff  = [r["diff_approx"] for r in rows if r["diff_approx"] is not None]
    total_diff = sum(has_diff) if has_diff else None
    total_coin = sum(r["coin_diff"] or 0 for r in rows)
    total_spin = sum(r["total_start"] or 0 for r in rows)
    prob_vals  = [r["syn_prob"] for r in rows if r["syn_prob"]]
    avg_prob   = f"1/{sum(prob_vals)/len(prob_vals):.0f}" if prob_vals else "---"

    diff_cls = _sign_cls(total_diff)
    diff_disp = _sign(total_diff) + "枚" if total_diff is not None else "---"

    summary_html = f"""
<div class="summary">
  <div class="stat-box"><div class="val">{total}</div><div class="lbl">収集台数</div></div>
  <div class="stat-box"><div class="val">{played}</div><div class="lbl">稼働台数</div></div>
  <div class="stat-box"><div class="val {diff_cls}">{diff_disp}</div><div class="lbl">合計推定差枚数</div></div>
  <div class="stat-box"><div class="val">{total_coin:,}</div><div class="lbl">合計出メダル</div></div>
  <div class="stat-box"><div class="val">{total_spin:,}</div><div class="lbl">合計回転数</div></div>
  <div class="stat-box"><div class="val">{avg_prob}</div><div class="lbl">平均合成確率</div></div>
</div>"""

    # テーブル行
    table_rows = ""
    for r in rows:
        tag  = f'<span class="tag tag-{r["denom"].lower()}">{r["denom"]}</span>'
        cnt  = model_count.get((r["machine_name"], r["denom"]), 1)
        name = html_lib.escape(r["machine_name"])
        da   = r["diff_approx"]
        fs   = r["first_start"]

        table_rows += (
            f'<tr data-name="{html_lib.escape(r["machine_name"])}" data-denom="{r["denom"]}">'
            f'<td data-v="{r["machine_no"]}">{r["machine_no"]:04d}</td>'
            f'<td class="L">{name}（{cnt}台）{tag}</td>'
            + _td(fs,  f"{fs:,}G" if fs is not None else "---")
            + _td(da,  _diff_approx_fmt(da), _sign_cls(da))
            + _td(r["coin_diff"],   _fmt(r["coin_diff"]))
            + _td(r["total_start"], _fmt(r["total_start"]))
            + _td(r["final_start"], _fmt(r["final_start"]))
            + _td(r["bb_count"],    _fmt(r["bb_count"]))
            + _td(r["rb_count"],    _fmt(r["rb_count"]))
            + _td(r["art_count"],   _fmt(r["art_count"]))
            + _td(r["bb_prob"],     _prob(r["bb_prob"]))
            + _td(r["syn_prob"],    _prob(r["syn_prob"]))
            + _td(r["art_games"],   _fmt(r["art_games"]))
            + "</tr>"
        )

    prev_date = (date(int(d[:4]), int(d[4:6]), int(d[6:])) - timedelta(days=1)).strftime("%Y%m%d")
    next_date = (date(int(d[:4]), int(d[4:6]), int(d[6:])) + timedelta(days=1)).strftime("%Y%m%d")

    html = f"""<!DOCTYPE html><html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>パチスロ {date_disp}（{wd}）</title>
<style>{CSS}</style></head><body><div class="container">
<h1>🎰 パチスロ台別データ</h1>
<div class="sub">{date_disp}（{wd}）| オリエンタルパサージュ自由が丘</div>
<div class="nav">
  <a href="daily_{prev_date}.html">◀ 前日</a>
  <a href="daily_{next_date}.html">翌日 ▶</a>
  <a href="../stats.html">📊 統計・分析</a>
  <a href="../latest.html">最新</a>
</div>
{summary_html}
<div class="card">
<h2>台別データ一覧　<small style="font-weight:normal;color:#666">列ヘッダーでソート</small></h2>
<div class="filter-bar">
  <input id="filter-name" type="text" placeholder="機種名で絞り込み（例：北斗の拳）" autocomplete="off">
  <div class="denom-filter">
    <label><input type="radio" name="fd" value="all" checked> 全て</label>
    <label><input type="radio" name="fd" value="S20"> 20スロ</label>
    <label><input type="radio" name="fd" value="S5"> 5スロ</label>
  </div>
  <span id="filter-count">{total}台表示中</span>
</div>
<div class="table-wrap">
<table class="sortable filterable" data-default-col="0" data-default-asc="true"><thead><tr>
  <th>台番</th>
  <th class="L">機種名</th>
  <th>初当たり<br><small>（リセット判別）</small></th>
  <th>推定差枚数<br><small>（±500枚単位）</small></th>
  <th>出メダル<br><small>（ボーナス計）</small></th>
  <th>総回転</th><th>最終回転</th>
  <th>BB</th><th>RB</th><th>ART</th>
  <th>BB確率</th><th>合成確率</th><th>ARTゲーム数</th>
</tr></thead><tbody>
{table_rows}
</tbody></table>
</div>
</div>
<div class="footer">データ: papimo.jp | 生成: {date_disp}</div>
</div>{JS}</body></html>"""

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    out = ARCHIVE_DIR / f"daily_{target_date}.html"
    out.write_text(html, encoding="utf-8")
    return out


# ── 統計HTML ──────────────────────────────────────────────────────────────────

def generate_stats_html() -> Path:
    conn = get_connection()
    c = conn.cursor()

    today     = date.today()
    week_ago  = (today - timedelta(days=7)).strftime("%Y%m%d")
    month_ago = (today - timedelta(days=30)).strftime("%Y%m%d")

    # 収集済み日付一覧
    dates = [r[0] for r in c.execute(
        "SELECT DISTINCT date FROM daily_records ORDER BY date DESC"
    ).fetchall()]

    # ── 日次推移（デノミ別） ──────────────────────────────────
    daily_rows = c.execute("""
        SELECT date, denom,
               COUNT(*) as total,
               COUNT(CASE WHEN total_start > 0 THEN 1 END) as played,
               SUM(diff_approx)  as sum_diff,
               AVG(diff_approx)  as avg_diff,
               AVG(first_start)  as avg_first_start,
               SUM(total_start)  as sum_spin,
               AVG(total_start)  as avg_spin,
               AVG(syn_prob)     as avg_prob
        FROM daily_records
        GROUP BY date, denom
        ORDER BY date DESC, denom
    """).fetchall()

    daily_table_rows = ""
    for r in daily_rows:
        d = r["date"]
        dd = f"{d[:4]}/{d[4:6]}/{d[6:]}"
        try:
            wd = "月火水木金土日"[date(int(d[:4]), int(d[4:6]), int(d[6:])).weekday()]
        except Exception:
            wd = ""
        sd  = r["sum_diff"]
        tag = f'<span class="tag tag-{r["denom"].lower()}">{r["denom"]}</span>'
        daily_table_rows += (
            f'<tr>'
            f'<td class="L"><a href="archive/daily_{d}.html">{dd}（{wd}）</a>{tag}</td>'
            f'<td>{r["played"]}/{r["total"]}</td>'
            + _td(sd, _sign(sd) + "枚" if sd is not None else "---", _sign_cls(sd))
            + _td(r["avg_diff"],
                  f"{r['avg_diff']:+,.0f}枚/台" if r["avg_diff"] is not None else "---",
                  _sign_cls(r["avg_diff"]))
            + _td(r["avg_first_start"],
                  f"{r['avg_first_start']:.0f}G" if r["avg_first_start"] is not None else "---")
            + _td(r["sum_spin"],  _fmt(r["sum_spin"])  if r["sum_spin"]  else "---")
            + _td(r["avg_spin"],  f"{r['avg_spin']:.0f}" if r["avg_spin"] else "---")
            + _td(r["avg_prob"],  _prob(r["avg_prob"]) if r["avg_prob"]  else "---")
            + "</tr>"
        )

    # ── 機種別集計 ────────────────────────────────────────────
    def get_agg(period_start: str):
        return c.execute("""
            SELECT machine_name, denom,
                   COUNT(DISTINCT date)  as days,
                   COUNT(*)              as total_machines,
                   AVG(coin_diff)        as avg_coin,
                   AVG(total_start)      as avg_start,
                   AVG(bb_count)         as avg_bb,
                   AVG(art_count)        as avg_art,
                   AVG(syn_prob)         as avg_prob,
                   SUM(coin_diff)        as sum_coin,
                   AVG(diff_approx)      as avg_diff,
                   SUM(diff_approx)      as sum_diff,
                   AVG(first_start)      as avg_first_start
            FROM daily_records
            WHERE date >= ?
            GROUP BY machine_name, denom
            ORDER BY denom, machine_name
        """, (period_start,)).fetchall()

    agg_week  = {(r["machine_name"], r["denom"]): r for r in get_agg(week_ago)}
    agg_month = {(r["machine_name"], r["denom"]): r for r in get_agg(month_ago)}
    agg_all   = {(r["machine_name"], r["denom"]): r for r in get_agg("00000000")}

    # ── 台番末尾分析 ──────────────────────────────────────────
    def get_digit_agg(period_start: str):
        return c.execute("""
            SELECT machine_no % 10  as last_digit,
                   denom,
                   COUNT(*)              as cnt,
                   COUNT(DISTINCT date)  as days,
                   AVG(diff_approx)      as avg_diff,
                   SUM(diff_approx)      as sum_diff,
                   AVG(total_start)      as avg_start,
                   SUM(total_start)      as sum_start,
                   COUNT(CASE WHEN diff_approx > 0 THEN 1 END) as pos_cnt
            FROM daily_records
            WHERE date >= ?
            GROUP BY last_digit, denom
            ORDER BY denom, last_digit
        """, (period_start,)).fetchall()

    digit_week  = get_digit_agg(week_ago)
    digit_month = get_digit_agg(month_ago)
    digit_all   = get_digit_agg("00000000")
    conn.close()

    def machine_table_rows(agg):
        html = ""
        for (name, denom), r in agg.items():
            tag = f'<span class="tag tag-{denom.lower()}">{denom}</span>'
            ad  = r["avg_diff"]
            ac  = r["avg_coin"]
            html += (
                "<tr>"
                f'<td class="L">{html_lib.escape(name)}{tag}</td>'
                f'<td>{r["days"]}</td>'
                + _td(ad, f"{ad:+,.0f}枚" if ad is not None else "---", _sign_cls(ad))
                + _td(r["sum_diff"],
                      _sign(round(r["sum_diff"])) + "枚" if r["sum_diff"] is not None else "---",
                      _sign_cls(r["sum_diff"]))
                + _td(r["avg_first_start"],
                      f"{r['avg_first_start']:.0f}G" if r["avg_first_start"] is not None else "---")
                + _td(r["avg_start"], _fmt(r["avg_start"], 0) if r["avg_start"] else "---")
                + _td(r["avg_bb"],    _fmt(r["avg_bb"],    1) if r["avg_bb"]    else "---")
                + _td(r["avg_art"],   _fmt(r["avg_art"],   1) if r["avg_art"]   else "---")
                + _td(r["avg_prob"],  _prob(r["avg_prob"]) if r["avg_prob"]     else "---")
                + "</tr>"
            )
        return html

    def digit_table_html(digit_rows, title):
        # S20=0〜9、S5=10〜19 の複合キーで末尾列をソート → S20の0-8→S5の0-8順になる
        denom_offset = {"S20": 0, "S5": 10}
        label = {"S20": "20スロ", "S5": "5スロ"}
        rows_html = ""
        for r in digit_rows:
            dn = r["denom"]
            sort_key = denom_offset.get(dn, 20) + r["last_digit"]
            d_tag = f'<span class="tag tag-{dn.lower()}">{label.get(dn, dn)}</span>'
            ad = r["avg_diff"]
            win_rate = f'{r["pos_cnt"]/r["cnt"]*100:.0f}%' if r["cnt"] else "---"
            rows_html += (
                f'<tr>'
                f'<td data-v="{sort_key}"><b>{r["last_digit"]}</b></td>'
                f'<td>{d_tag}</td>'
                f'<td>{r["cnt"]}</td>'
                f'<td>{r["days"]}</td>'
                + _td(ad, f"{ad:+,.0f}枚" if ad is not None else "---", _sign_cls(ad))
                + _td(r["sum_diff"],
                      _sign(round(r["sum_diff"])) + "枚" if r["sum_diff"] is not None else "---",
                      _sign_cls(r["sum_diff"]))
                + _td(r["avg_start"], f'{r["avg_start"]:.0f}G' if r["avg_start"] else "---")
                + _td(r["sum_start"], _fmt(r["sum_start"]) if r["sum_start"] else "---")
                + f'<td>{win_rate}</td>'
                + "</tr>"
            )
        return f"""
<div class="card">
<h2>{title}</h2>
<div class="table-wrap">
<table class="sortable" data-default-col="0" data-default-asc="true"><thead><tr>
  <th>末尾</th><th>レート</th><th>データ数</th><th>日数</th>
  <th>平均推定差枚数</th><th>累計推定差枚数</th>
  <th>平均回転数</th><th>合計回転数</th><th>プラス率</th>
</tr></thead><tbody>
{rows_html}
</tbody></table>
</div>
</div>"""

    def machine_table(agg, title):
        return f"""
<div class="card">
<h2>{title}</h2>
<div class="table-wrap">
<table class="sortable" data-default-col="2" data-default-asc="false"><thead><tr>
  <th class="L">機種名</th><th>日数</th>
  <th>平均推定差枚数/台</th><th>累計推定差枚数</th>
  <th>平均初当たり</th>
  <th>平均総回転</th><th>平均BB</th><th>平均ART</th><th>平均合成確率</th>
</tr></thead><tbody>
{machine_table_rows(agg)}
</tbody></table>
</div>
</div>"""

    latest_date = dates[0] if dates else "---"
    d = latest_date
    date_disp = f"{d[:4]}/{d[4:6]}/{d[6:]}" if len(d) == 8 else d

    html = f"""<!DOCTYPE html><html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>パチスロ 統計・分析</title>
<style>{CSS}</style></head><body><div class="container">
<h1>📊 パチスロ 統計・分析</h1>
<div class="sub">オリエンタルパサージュ自由が丘 | 最新: {date_disp} | 収集日数: {len(dates)}日</div>
<div class="nav">
  <a href="latest.html">📅 最新日次</a>
</div>

<div class="card">
<h2>日次推移　<small style="font-weight:normal;color:#666">直近60日</small></h2>
<div class="table-wrap">
<table class="sortable" data-default-col="0" data-default-asc="false"><thead><tr>
  <th class="L">日付</th><th>稼働/収集</th>
  <th>合計推定差枚数</th><th>平均推定差枚数/台</th>
  <th>平均初当たり</th>
  <th>合計回転数</th><th>平均回転数/台</th><th>平均合成確率</th>
</tr></thead><tbody>
{daily_table_rows}
</tbody></table>
</div>
</div>

{digit_table_html(digit_week,  "台番末尾分析 週次（直近7日）")}
{digit_table_html(digit_month, "台番末尾分析 月次（直近30日）")}
{digit_table_html(digit_all,   "台番末尾分析 全期間")}

{machine_table(agg_week,  "機種別週次平均（直近7日）")}
{machine_table(agg_month, "機種別月次平均（直近30日）")}
{machine_table(agg_all,   "機種別全期間平均")}

<div class="footer">データ: papimo.jp | 生成: {today.strftime("%Y/%m/%d")}</div>
</div>{JS}</body></html>"""

    out = REPORT_DIR / "stats.html"
    out.write_text(html, encoding="utf-8")
    return out


def update_latest(target_date: str):
    rel_path = f"archive/daily_{target_date}.html"
    html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url={rel_path}">
<title>最新データ</title>
</head><body>
<p><a href="{rel_path}">最新データを開く</a></p>
</body></html>"""
    (REPORT_DIR / "latest.html").write_text(html, encoding="utf-8")
