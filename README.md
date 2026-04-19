1. 說明

- 這是一個新的 repo，用途是使用 GitHub Actions 每天固定時間去跑 fantasy_daily.py
- 架構如下:
  - Trigger: 每天定時 (Cron) 或 手動推代碼。
  - Environment: GitHub Runner 啟動 Python 環境（uv 管理）。
  - Data Fetch: 透過 yahoo-fantasy-api 抓取球員數據。
  - 包含己方與敵方當日球員配置、當日自由球員名單
  - 計分指標（打擊）：R, HR, RBI, SB, OBP, OPS
  - 計分指標（投球）：QS, SV+HLD, K, ERA, WHIP, K/BB
  - AI Analysis: 將數據餵給 Claude Opus 4.6，並產出以下。
  - 配置建議(如誰該上場誰不該上場)
  - 自由球員撿取建議(自由球員有沒有適合撿來補強目前陣容缺乏數據)
  - 勝率分析
  - Notification: 呼叫 LINE Messaging API 推送結果。
  - Storage（選填）: 將每日數據與建議寫入 Google Sheets 留存。

2. 檔案結構

```
Yahoo_fantasy_API/
├── fantasy_daily.py       # 主程式
├── fantasy_daily.yaml     # GitHub Actions workflow
├── pyproject.toml         # uv 專案設定與依賴
├── uv.lock                # uv lock file（執行 uv sync 後自動產生）
├── config.yaml            # 計分指標、自由球員設定、Google Sheets 設定
├── .env                   # 機敏變數（不進 git）
├── .env.example           # 環境變數範本
└── oauth2.json            # Yahoo OAuth token（不進 git，執行時動態寫入）
```

3. 地端測試方法

### 前置步驟

**Step 1：安裝 uv（只需做一次）**
```bash
winget install astral-sh.uv
```

**Step 2：建立乾淨的虛擬環境並安裝依賴**

若是全新安裝（或想重建乾淨環境）：
```bash
cd Yahoo_fantasy_API
# 若已有舊的 .venv，先刪除
rm -rf .venv
uv sync
```
`uv sync` 會自動建立 `.venv` 虛擬環境並安裝所有依賴，產生 `uv.lock`。

啟用虛擬環境（可選，`uv run` 會自動使用 `.venv`，不需手動啟用）：
```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (CMD)
.venv\Scripts\activate.bat
# macOS / Linux
source .venv/bin/activate
```

> 注意：若 `uv sync` 出現 access denied 錯誤，代表 `.venv` 被其他程序（IDE、terminal）佔用，關閉後重試。

**Step 3：設定環境變數**
```bash
cp .env.example .env
```
編輯 `.env`，填入以下變數：

| 變數名稱 | 說明 |
|---|---|
| `YAHOO_OAUTH_JSON` | yahoo oauth2.json 的完整 JSON 字串 |
| `YAHOO_LEAGUE_ID` | 聯盟 ID（在 Yahoo Fantasy 網址可找到） |
| `YAHOO_TEAM_ID` | 你的隊伍 ID |
| `ANTHROPIC_API_KEY` | Anthropic Console 取得（console.anthropic.com） |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers 後台取得 |
| `LINE_USER_ID` | 你的 LINE User ID |
| `GOOGLE_SHEET_ID` | （選填）Google Sheet 的 ID，留空則跳過寫入 |

**Step 4：取得 Yahoo OAuth Token**

首次需要手動跑一次 OAuth 授權，產生 `oauth2.json`：

**Step 4-1：建立 Yahoo Developer App，取得 Consumer Key / Secret**

1. 前往 https://developer.yahoo.com/apps/ 並登入 Yahoo 帳號
2. 點 **Create an App**，填入以下設定：
   - **Application Name**: 隨意（例如 `fantasy-bot`）
   - **Application Type**: `Installed Application`
   - **Callback Domain**: `localhost`
   - **API Permissions**: 勾選 `Fantasy Sports` → `Read`
3. 建立後頁面會顯示 **Consumer Key** 和 **Consumer Secret**，複製備用

**Step 4-2：執行 OAuth 授權**

先建立只含 consumer key/secret 的 `oauth2.json`：
```json
{
    "consumer_key": "你的_consumer_key",
    "consumer_secret": "你的_consumer_secret"
}
```

再跑授權：
```bash
uv run python -c "
from yahoo_oauth import OAuth2
sc = OAuth2(None, None, from_file='oauth2.json')
"
```
瀏覽器開啟後登入對應的 Yahoo 帳號完成授權，`oauth2.json` 會自動更新加入 token。
之後把 `oauth2.json` 的內容整個複製（單行 JSON），貼進 `.env` 的 `YAHOO_OAUTH_JSON=` 後面。

> 注意：`YAHOO_LEAGUE_ID` 格式為 `458.l.XXXXXX`，`YAHOO_TEAM_ID` 格式為 `458.l.XXXXXX.t.N`，可從 Yahoo Fantasy 網址取得。

### 執行測試

```bash
uv run python fantasy_daily.py
```

### 只測試 Claude 分析（不抓 Yahoo 數據）

可以在 `fantasy_daily.py` 的 `if __name__ == "__main__"` 下方加入 mock 數據快速測試 Claude prompt，不需要 Yahoo 認證。

### Google Sheets 設定（選填）

若要啟用 Google Sheets 寫入：
1. 在 [Google Cloud Console](https://console.cloud.google.com) 建立專案，啟用 Google Sheets API。
2. 建立 Service Account，下載 `service_account.json`，放到專案根目錄（不進 git）。
3. 把 Service Account 的 email 加入你的 Google Sheet 的編輯權限。
4. 在 `config.yaml` 的 `google_sheets.sheet_id` 填入 Sheet ID（網址中的那串字）。