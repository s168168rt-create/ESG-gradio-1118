# ============================================================
#  公開資訊 CSV 資料瀏覽器 (Gradio + FastAPI)
#  PWA(可安裝、離線頁、Service Worker)+ RWD(手機 / 平板 / 桌機)
#  部署到 Render 或本機:python app.py
# ============================================================
import io
import os
import tempfile
import time
from pathlib import Path

import gradio as gr
import pandas as pd
import plotly.express as px
import requests
import urllib3
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # verify=False 的警告

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

DEFAULT_URL = "https://mopsfin.twse.com.tw/opendata/t187ap46_L_1.csv"  # 換連結
MAX_PREVIEW_ROWS = 2000    # 表格最多顯示列數(避免手機瀏覽器卡頓)
CACHE_TTL = 600            # 同一連結 10 分鐘內不重複下載
_cache: dict[str, tuple[float, pd.DataFrame, int]] = {}


# ------------------------------------------------------------
# 資料處理
# ------------------------------------------------------------
def fetch_csv(url: str) -> tuple[pd.DataFrame, int]:
    """下載 CSV → 存成 data01.csv → 讀入(繁體中文編碼)→ dropna。回傳 (df, 原始列數)。"""
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1].copy(), hit[2]

    response = requests.get(url, verify=False, timeout=30)
    response.raise_for_status()
    try:
        with open("data01.csv", "wb") as f:
            f.write(response.content)
    except OSError:
        pass                                              # 唯讀檔案系統時略過存檔

    last_err = None
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            raw = pd.read_csv(io.BytesIO(response.content), encoding=enc)
            break
        except Exception as e:                            # 編碼不符就換下一個
            last_err = e
    else:
        raise last_err

    df = raw.dropna().reset_index(drop=True)
    _cache[url] = (time.time(), df, len(raw))
    return df.copy(), len(raw)


def stat_cards(total_raw, df: pd.DataFrame, shown: int | None = None) -> str:
    num_cols = df.select_dtypes("number").shape[1]
    shown = len(df) if shown is None else shown
    items = [
        ("📄 資料筆數", f"{shown:,}"),
        ("🧱 欄位數", f"{df.shape[1]:,}"),
        ("🔢 數值欄位", f"{num_cols:,}"),
        ("🧹 移除空值列", f"{max(total_raw - len(df), 0):,}" if total_raw is not None else "-"),
    ]
    cards = "".join(
        f"<div class='card'><div class='card-label'>{k}</div><div class='card-value'>{v}</div></div>"
        for k, v in items
    )
    return f"<div class='cards'>{cards}</div>"


def to_preview(df: pd.DataFrame) -> pd.DataFrame:
    return df.head(MAX_PREVIEW_ROWS)


def column_summary(df: pd.DataFrame) -> pd.DataFrame:
    summary = df.describe(include="all").T.reset_index()
    summary = summary.rename(columns={"index": "欄位"})
    summary.insert(1, "型別", [str(df[c].dtype) for c in summary["欄位"]])
    return summary.astype(object).where(summary.notna(), "")


def apply_filter(df: pd.DataFrame, keyword: str, column: str) -> pd.DataFrame:
    keyword = (keyword or "").strip()
    if not keyword:
        return df
    if column and column != "(全部欄位)":
        mask = df[column].astype(str).str.contains(keyword, case=False, na=False, regex=False)
    else:
        mask = df.astype(str).apply(
            lambda s: s.str.contains(keyword, case=False, na=False, regex=False)
        ).any(axis=1)
    return df[mask]


# ------------------------------------------------------------
# Gradio 事件函式
# ------------------------------------------------------------
def load_data(url):
    try:
        df, raw_count = fetch_csv((url or "").strip())
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:120]}"          # 避免超長錯誤訊息撐破手機版面
        gr.Warning(f"載入失敗,請確認連結是否正確或稍後再試。({msg})")
        return (None, "", f"❌ 載入失敗,請確認連結是否正確。\n\n`{msg}`", pd.DataFrame(), pd.DataFrame(),
                gr.update(choices=["(全部欄位)"], value="(全部欄位)"),
                gr.update(choices=[], value=None), gr.update(choices=[], value=None),
                None, None)

    cols = df.columns.tolist()
    num_cols = df.select_dtypes("number").columns.tolist()
    default_label = next((c for c in cols if c not in num_cols), cols[0])
    default_value = next((c for c in num_cols if c != default_label), None)
    return (
        df,
        stat_cards(raw_count, df),
        f"✅ 載入成功,共 {len(df):,} 筆資料、{len(cols)} 個欄位",
        to_preview(df),
        column_summary(df),
        gr.update(choices=["(全部欄位)"] + cols, value="(全部欄位)"),
        gr.update(choices=cols, value=default_label),
        gr.update(choices=num_cols, value=default_value),
        None,
        None,
    )


def search(df, keyword, column):
    if df is None:
        return pd.DataFrame(), "<div class='cards'></div>"
    result = apply_filter(df, keyword, column)
    return to_preview(result), stat_cards(None, df, shown=len(result))


def export_csv(df, keyword, column):
    if df is None:
        gr.Warning("請先載入資料")
        return None
    filtered = apply_filter(df, keyword, column)
    path = tempfile.NamedTemporaryFile(suffix=".csv", prefix="filtered_", delete=False).name
    filtered.to_csv(path, index=False, encoding="utf-8-sig")   # utf-8-sig:Excel 開啟不亂碼
    return path


def draw_chart(df, label_col, value_col, top_n, ascending):
    if df is None or not label_col or not value_col:
        gr.Warning("請先載入資料並選擇欄位(數值欄位需為數字)")
        return None
    if label_col == value_col:
        gr.Warning("標籤欄位與數值欄位不能相同,請重新選擇")
        return None
    data = df[[label_col, value_col]].copy()
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce")
    data = data.dropna().sort_values(value_col, ascending=ascending).head(int(top_n))
    data[label_col] = data[label_col].astype(str)
    fig = px.bar(
        data, x=value_col, y=label_col, orientation="h", text=value_col,
        color=value_col, color_continuous_scale="Tealgrn",
        title=f"{value_col} ─ {'最小' if ascending else '最大'} {int(top_n)} 名",
    )
    fig.update_layout(
        autosize=True,                                    # RWD:隨容器寬度縮放
        yaxis=dict(autorange="reversed", type="category", automargin=True, title=None),
        xaxis=dict(automargin=True),
        coloraxis_showscale=False, height=max(360, 26 * len(data) + 120),
        margin=dict(l=8, r=24, t=72, b=8), template="plotly_white",
        title=dict(font=dict(size=16)),
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    return fig


# ------------------------------------------------------------
# PWA:<head> 注入(manifest、主題色、iOS 設定、Service Worker、安裝按鈕)
# ------------------------------------------------------------
HEAD = """
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0f766e">
<meta name="application-name" content="CSV 瀏覽器">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="CSV 瀏覽器">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="/static/icons/apple-touch-icon.png">
<link rel="icon" type="image/png" href="/static/icons/icon-192.png">
<script>
(function () {
  // Gradio 會在頁面載入後才注入這段 <head>,load 事件可能已經過了,所以用 readyState 判斷
  function onReady(fn) {
    if (document.readyState === "complete") fn(); else window.addEventListener("load", fn);
  }

  // 1) 註冊 Service Worker
  if ("serviceWorker" in navigator) {
    onReady(function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function (e) {
        console.warn("SW 註冊失敗", e);
      });
    });
  }

  var standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone) return;                                   // 已安裝 / 以 App 開啟,不顯示提示

  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) {} }

  function makeBar(text, btnText, onClick) {
    var bar = document.createElement("div");
    bar.className = "pwa-bar";
    bar.innerHTML = "<span></span><button class='pwa-go'></button><button class='pwa-x' aria-label='關閉'>✕</button>";
    bar.querySelector("span").textContent = text;
    var go = bar.querySelector(".pwa-go");
    if (btnText) { go.textContent = btnText; go.onclick = function () { onClick(bar); }; } else { go.remove(); }
    bar.querySelector(".pwa-x").onclick = function () { bar.remove(); store("pwa-dismissed", "1"); };
    document.body.appendChild(bar);
  }

  // 2) Android / 桌面 Chrome、Edge:自訂「安裝 App」按鈕
  var deferred = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    if (store("pwa-dismissed")) return;
    makeBar("把它安裝成 App,下次一鍵開啟", "安裝", function (bar) {
      deferred.prompt();
      deferred.userChoice.finally(function () { deferred = null; bar.remove(); });
    });
  });
  window.addEventListener("appinstalled", function () {
    var b = document.querySelector(".pwa-bar"); if (b) b.remove();
  });

  // 3) iOS Safari:沒有安裝事件,改顯示操作教學
  var ua = navigator.userAgent;
  var isIOS = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  var isSafari = /safari/i.test(ua) && !/crios|fxios|edgios/i.test(ua);
  if (isIOS && isSafari && !store("pwa-dismissed")) {
    onReady(function () {
      setTimeout(function () { makeBar("安裝到主畫面:點下方「分享」→「加入主畫面」"); }, 1500);
    });
  }
})();
</script>
"""

# ------------------------------------------------------------
# RWD:CSS
# ------------------------------------------------------------
CSS = """
:root {--brand: #0f766e; --brand2: #2563eb;}
html, body {-webkit-text-size-adjust: 100%;}
.gradio-container {
  max-width: 1200px !important; margin: auto;
  padding-left: max(12px, env(safe-area-inset-left)) !important;
  padding-right: max(12px, env(safe-area-inset-right)) !important;
  padding-bottom: calc(24px + env(safe-area-inset-bottom)) !important;
}
footer {display: none !important;}
.toast-wrap {left: 8px !important; right: 8px !important; width: auto !important;
             max-width: calc(100vw - 16px) !important; box-sizing: border-box;}
.toast-item, .toast-body {max-width: 100% !important; box-sizing: border-box;}
.toast-body, .toast-text, .prose, .prose code {overflow-wrap: anywhere; word-break: break-word;}

/* 標題 */
.hero {padding: clamp(18px, 4vw, 32px); border-radius: 18px; color: #fff;
       background: linear-gradient(135deg, var(--brand) 0%, var(--brand2) 100%);
       box-shadow: 0 10px 30px rgba(37,99,235,.25); margin-bottom: 12px;
       padding-top: calc(clamp(18px, 4vw, 32px) + env(safe-area-inset-top));}
.hero h1 {margin: 0 0 6px; font-size: clamp(20px, 5.2vw, 28px); line-height: 1.3; color: #fff;}
.hero p {margin: 0; opacity: .92; font-size: clamp(13px, 3.6vw, 15px); line-height: 1.6;}

/* 統計卡片:自動換行 */
.cards {display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 6px 0 12px;}
.card {background: var(--background-fill-primary); border: 1px solid var(--border-color-primary);
       border-radius: 14px; padding: 14px 16px; box-shadow: 0 2px 8px rgba(0,0,0,.05);}
.card-label {font-size: 13px; opacity: .7; margin-bottom: 4px;}
.card-value {font-size: clamp(20px, 5vw, 26px); font-weight: 700; color: var(--brand);}

/* 表格與圖表:橫向可捲動,不撐破版面 */
.table-wrap, .plot-box {min-width: 0 !important; max-width: 100%; overflow-x: auto; contain: inline-size;}

/* 平板以下:多欄 Row 改為直向堆疊 */
@media (max-width: 820px) {
  .stack {flex-wrap: wrap !important;}
  .stack > * {min-width: 100% !important; flex: 1 1 100% !important;}
  .stack.pair > * {min-width: calc(50% - 8px) !important; flex: 1 1 calc(50% - 8px) !important;}
}

/* 手機 */
@media (max-width: 560px) {
  .gradio-container {padding-left: 8px !important; padding-right: 8px !important;}
  .cards {grid-template-columns: repeat(2, 1fr); gap: 10px;}
  .card {padding: 12px;}
  .card-label {font-size: 12px;}
  .stack.pair > * {min-width: 100% !important; flex: 1 1 100% !important;}
  button, .gradio-container button {min-height: 44px;}              /* 觸控目標 ≥ 44px */
  input, textarea, select {font-size: 16px !important;}             /* 避免 iOS 聚焦時自動放大 */
  .tab-wrapper, .tab-container {overflow-x: auto;}
}

/* PWA 安裝提示列 */
.pwa-bar {position: fixed; left: 50%; transform: translateX(-50%); z-index: 9999;
          bottom: calc(14px + env(safe-area-inset-bottom)); width: min(92vw, 520px);
          display: flex; align-items: center; gap: 10px; padding: 10px 12px 10px 16px;
          background: #0f172a; color: #fff; border-radius: 14px; font-size: 14px; line-height: 1.5;
          box-shadow: 0 10px 30px rgba(0,0,0,.35);}
.pwa-bar span {flex: 1;}
.pwa-bar button {border: 0; cursor: pointer; border-radius: 10px; min-height: 40px; font: inherit;}
.pwa-bar .pwa-go {background: #14b8a6; color: #042f2e; font-weight: 700; padding: 0 16px;}
.pwa-bar .pwa-x {background: transparent; color: #cbd5e1; padding: 0 8px; font-size: 16px;}

/* 以 App 模式開啟時,避開瀏海 */
@media (display-mode: standalone) {body {overscroll-behavior-y: contain;}}
"""

theme = gr.themes.Soft(primary_hue="teal", secondary_hue="blue", neutral_hue="slate",
                       font=[gr.themes.GoogleFont("Noto Sans TC"), "sans-serif"])

# Gradio 6 起 theme / css / head 改由 launch() / mount_gradio_app() 傳入
GR6 = int(gr.__version__.split(".")[0]) >= 6
_style = {"theme": theme, "css": CSS, "head": HEAD}

# ------------------------------------------------------------
# 介面
# ------------------------------------------------------------
with gr.Blocks(title="公開資訊 CSV 資料瀏覽器", **({} if GR6 else _style)) as demo:
    df_state = gr.State(None)

    gr.HTML("""
    <div class="hero">
      <h1>📊 公開資訊 CSV 資料瀏覽器</h1>
      <p>輸入 CSV 連結 → 一鍵載入 → 搜尋、統計、繪圖、下載。可安裝成 App,手機、平板、電腦都好用。</p>
    </div>""")

    with gr.Row(equal_height=True, elem_classes="stack"):
        url_box = gr.Textbox(label="CSV 連結", value=DEFAULT_URL, scale=5, lines=1,
                             max_lines=1)
        load_btn = gr.Button("🚀 載入資料", variant="primary", scale=1)
    status = gr.Markdown("")
    cards = gr.HTML("")

    with gr.Tabs():
        with gr.Tab("🔎 資料表"):
            with gr.Row(elem_classes="stack pair"):
                with gr.Column(scale=3, min_width=200):
                    keyword = gr.Textbox(label="關鍵字搜尋", placeholder="例如:台積電、2330 …")
                with gr.Column(scale=2, min_width=160):
                    search_col = gr.Dropdown(label="搜尋欄位", choices=["(全部欄位)"], value="(全部欄位)")
                with gr.Column(scale=1, min_width=120):
                    search_btn = gr.Button("搜尋", variant="primary")
            table = gr.Dataframe(label="資料預覽", interactive=False, wrap=True,
                                 max_height=520, elem_classes="table-wrap")
            with gr.Row(elem_classes="stack"):
                with gr.Column(min_width=200):
                    dl_btn = gr.Button("⬇️ 產生篩選結果 CSV")
                with gr.Column(min_width=200):
                    dl_file = gr.File(label="下載檔案", interactive=False)

        with gr.Tab("📈 圖表"):
            with gr.Row(elem_classes="stack pair"):
                with gr.Column(min_width=160):
                    label_col = gr.Dropdown(label="標籤欄位 (Y 軸)", choices=[])
                with gr.Column(min_width=160):
                    value_col = gr.Dropdown(label="數值欄位 (X 軸)", choices=[])
            with gr.Row(elem_classes="stack"):
                with gr.Column(scale=3, min_width=240):
                    top_n = gr.Slider(5, 50, value=15, step=1, label="顯示前 N 筆")
                with gr.Column(scale=1, min_width=160):
                    asc = gr.Checkbox(label="由小到大", value=False)
            plot_btn = gr.Button("繪製圖表", variant="primary")
            plot = gr.Plot(label="長條圖", elem_classes="plot-box")

        with gr.Tab("🧮 欄位統計"):
            summary = gr.Dataframe(label="describe() 摘要", interactive=False, wrap=True,
                                   elem_classes="table-wrap")

    load_outputs = [df_state, cards, status, table, summary,
                    search_col, label_col, value_col, plot, dl_file]
    load_btn.click(load_data, url_box, load_outputs)
    url_box.submit(load_data, url_box, load_outputs)
    demo.load(load_data, url_box, load_outputs)               # 開啟頁面時自動載入預設連結

    search_btn.click(search, [df_state, keyword, search_col], [table, cards])
    keyword.submit(search, [df_state, keyword, search_col], [table, cards])
    dl_btn.click(export_csv, [df_state, keyword, search_col], dl_file)
    plot_btn.click(draw_chart, [df_state, label_col, value_col, top_n, asc], plot)


# ------------------------------------------------------------
# FastAPI:PWA 檔案 + 掛載 Gradio
# ------------------------------------------------------------
app = FastAPI(title="CSV Viewer", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return JSONResponse({"status": "ok"})


@app.get("/manifest.webmanifest", include_in_schema=False)
@app.get("/manifest.json", include_in_schema=False)      # Gradio 預設的 <link rel=manifest> 指向這個路徑,一併提供
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Service Worker 必須由根路徑提供,才能控制整個網站(scope="/")
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/offline.html", include_in_schema=False)
def offline():
    return FileResponse(STATIC_DIR / "offline.html", media_type="text/html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "icons" / "icon-192.png", media_type="image/png")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 必須在自訂路由之後才掛載到 "/"
app = gr.mount_gradio_app(app, demo, path="/", **(_style if GR6 else {}))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)),
                proxy_headers=True, forwarded_allow_ips="*")   # Render 在 HTTPS 代理後方
