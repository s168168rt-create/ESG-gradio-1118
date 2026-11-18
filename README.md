# 📊 公開資訊 CSV 資料瀏覽器(PWA + RWD)

以 **Gradio + FastAPI** 製作的 CSV 資料瀏覽器。輸入 CSV 連結(預設為公開資訊觀測站 `t187ap46_L_1.csv`),即可搜尋、統計、繪圖並下載篩選結果。

- 📱 **RWD**:手機、平板、桌機自動調整版面
- 📲 **PWA**:可「安裝」到手機主畫面 / 電腦桌面,以獨立視窗開啟;離線時顯示專屬離線頁

## 功能

- 🚀 輸入 CSV 連結一鍵載入(自動處理繁體中文編碼:`utf-8-sig` → `utf-8` → `big5` → `cp950`)
- 🧹 自動移除含空值的列(`dropna`)
- 🔎 關鍵字搜尋(全部欄位或單一欄位),可下載篩選後的 CSV(Excel 開啟不亂碼)
- 📈 依任一數值欄位繪製前 N 名橫向長條圖
- 🧮 欄位型別與統計摘要
- ⚡ 同一連結 10 分鐘內使用記憶體快取,不重複下載

## 專案結構

```
.
├── app.py                      # 主程式(Gradio 介面 + FastAPI + PWA 路由)
├── requirements.txt
├── render.yaml                 # Render Blueprint(選用)
├── .python-version
├── static/
│   ├── manifest.webmanifest    # PWA 設定(名稱、圖示、主題色)
│   ├── sw.js                   # Service Worker
│   ├── offline.html            # 離線頁
│   └── icons/                  # 192 / 512 / maskable / apple-touch / svg
└── tools/make_icons.py         # 重新產生圖示(選用,需 pip install pillow numpy)
```

## 本機執行

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

開啟 http://127.0.0.1:7860 。`localhost` 也算安全來源,可直接測試 PWA 安裝。

## 部署到 Render

1. 把整個專案推到 GitHub(`static/` 資料夾務必一起上傳)。
2. Render → **New +** → **Web Service** → 選擇該 repo。
3. 設定:

   | 項目 | 值 |
   |---|---|
   | Runtime | Python 3 |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `python app.py` |
   | Health Check Path | `/healthz` |
   | Instance Type | Free |

4. 在 **Environment** 新增 `PYTHON_VERSION` = `3.12.7`。
5. **Create Web Service**,完成後以 `https://<名稱>.onrender.com` 開啟。

也可使用 `render.yaml`:Render 控制台 **New +** → **Blueprint**,指向此 repo 即可。

> Render 預設提供 HTTPS,正好滿足 PWA 的必要條件(Service Worker 只能在 HTTPS 或 localhost 運作)。
> 程式會讀取 Render 的 `PORT` 環境變數並監聽 `0.0.0.0`。

## 安裝成 App

| 平台 | 方式 |
|---|---|
| Android / Windows / macOS(Chrome、Edge) | 開啟網站後,畫面下方會出現「安裝」提示列;或點網址列右側的安裝圖示 |
| iPhone / iPad(Safari) | 點「分享」→「加入主畫面」(網頁會顯示操作提示) |

## PWA 架構說明

| 檔案 | 作用 |
|---|---|
| `/manifest.webmanifest`(及 `/manifest.json`) | 名稱、圖示、`display: standalone`、主題色 |
| `/sw.js` | 由根路徑提供,`scope="/"`。頁面導覽採「網路優先,離線顯示 `/offline.html`」;`/static/` 圖示等資源採「快取優先 + 背景更新」。Gradio 的 API、佇列、檔案下載一律不攔截,避免資料過期 |
| `<head>` 注入 | `manifest`、`theme-color`、iOS 的 `apple-touch-icon` 與 `apple-mobile-web-app-*`,以及註冊 SW、安裝提示的腳本 |

更新快取:修改 `static/sw.js` 內的 `VERSION`(例如 `v1` → `v2`),舊快取會在使用者下次開啟時自動清除。

> 資料需要連線到伺服器才能載入與計算,所以「離線」時只會顯示離線頁,無法瀏覽資料,這是預期行為。

## RWD 重點

- 版面寬度 `max-width: 1200px`,左右留白隨螢幕縮小
- ≤ 820px:多欄控制項改為直向堆疊;≤ 560px:統計卡片改為 2 欄、按鈕高度 ≥ 44px、輸入框字級 16px(避免 iOS 聚焦時自動放大)
- 表格可橫向捲動,圖表寬度自動縮放
- 支援瀏海螢幕安全區(`env(safe-area-inset-*)`)與深色模式

## 注意事項

- Render 免費方案閒置約 15 分鐘後休眠,再次開啟需等 30~60 秒喚醒。
- 檔案系統為暫存性質,`data01.csv` 重啟後會消失,但每次載入都會重新下載。
- 為相容部分政府網站憑證,下載時使用 `verify=False`(已關閉警告)。若資料來源憑證正常,建議在 `fetch_csv` 改為 `verify=True`。
- 更換預設資料來源:編輯 `app.py` 的 `DEFAULT_URL`。
