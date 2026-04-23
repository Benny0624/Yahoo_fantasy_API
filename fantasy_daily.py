import os
import json
import logging
from datetime import date

import yaml
from dotenv import load_dotenv
from yahoo_oauth import OAuth2
import yahoo_fantasy_api as yfa
import anthropic
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    BroadcastRequest, TextMessage as LineTextMessage,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

BATTING_CATS = config["stats"]["batting"]
PITCHING_CATS = config["stats"]["pitching"]


def get_free_agents(league):
    fa = {}
    for pos in config["free_agents"]["positions"]:
        count = config["free_agents"]["count"]
        fa[pos] = league.free_agents(pos)[:count]
    return fa


def write_to_google_sheets(today: str, roster, fa, advice: str):
    sheet_id = os.environ.get("GOOGLE_SHEET_ID") or config["google_sheets"]["sheet_id"]
    if not sheet_id:
        logger.info("GOOGLE_SHEET_ID 未設定，跳過寫入 Google Sheets")
        return

    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        creds = Credentials.from_service_account_info(json.loads(sa_json), scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    gc = gspread.authorize(creds)

    sh = gc.open_by_key(sheet_id)
    worksheet_name = config["google_sheets"]["worksheet_name"]
    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=10)

    ws.append_row([today, json.dumps(roster, ensure_ascii=False), json.dumps(fa, ensure_ascii=False), advice])
    logger.info("已寫入 Google Sheets")


def run_fantasy_advisor():
    # 1. Yahoo OAuth
    auth_content = os.environ.get("YAHOO_OAUTH_JSON")
    with open("oauth2.json", "w") as f:
        f.write(auth_content)

    sc = OAuth2(None, None, from_file="oauth2.json")
    gm = yfa.Game(sc, config["league"]["sport"])
    league = gm.to_league(os.environ.get("YAHOO_LEAGUE_ID"))
    team = league.to_team(os.environ.get("YAHOO_TEAM_ID"))

    # 2. 抓取數據
    roster = team.roster()
    fa = get_free_agents(league)

    # 3. Claude 分析
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    prompt = f"""
你是一位精簡的 Fantasy Baseball 顧問。
本聯盟計分指標：
  打擊：{", ".join(BATTING_CATS)}
  投球：{", ".join(PITCHING_CATS)}

我的目前陣容：
{json.dumps(roster, ensure_ascii=False, indent=2)}

可撿的自由球員：
{json.dumps(fa, ensure_ascii=False, indent=2)}

請根據今日賽程與球員近況，用繁體中文給出簡短建議，總字數控制在 {config["claude"]["max_words"]} 字以內：

【首發調整】
- 只指出「放板凳但今天應該上場」或「在場上但今天不該出賽」的球員，沒問題就說「首發無調整」。

【最值得撿的自由球員】
- 打擊推薦 1 人：姓名、理由一句話、對哪個指標最有幫助。
- 投手推薦 1 人：同上。
- 若沒有值得撿的就說「無推薦」。

【本週勝負預測】
- 一句話評估即可。

注意：總回覆必須在 {config["claude"]["max_words"]} 字以內，超過請刪減，絕對不可超字。
"""

    max_words = config["claude"]["max_words"]
    response = client.messages.create(
        model=config["claude"]["model"],
        max_tokens=max_words * 2,  # 每個中文字約 1–2 token，乘 2 留緩衝但仍有上限
        messages=[{"role": "user", "content": prompt}],
    )
    advice = response.content[0].text
    logger.info("Claude 分析完成")

    # 4. 寫入 Google Sheets（選填）
    today = str(date.today())
    write_to_google_sheets(today, roster, fa, advice)

    # 5. LINE 推播（單則上限 5000 字，超過自動分拆，每次最多 5 則）
    LINE_LIMIT = 5000
    full_text = f"⚾ Fantasy 每日戰報 {today}：\n\n{advice}"
    chunks = [full_text[i:i + LINE_LIMIT] for i in range(0, len(full_text), LINE_LIMIT)]

    configuration = Configuration(access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
    with ApiClient(configuration) as api_client:
        line_bot = MessagingApi(api_client)
        for batch_start in range(0, len(chunks), 5):
            batch = [LineTextMessage(text=c) for c in chunks[batch_start:batch_start + 5]]
            line_bot.broadcast(BroadcastRequest(messages=batch))
    logger.info("LINE 推播完成")


if __name__ == "__main__":
    run_fantasy_advisor()
