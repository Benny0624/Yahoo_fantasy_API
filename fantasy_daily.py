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
    PushMessageRequest, TextMessage as LineTextMessage,
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
你是一位專業的 Fantasy Baseball 數據分析師。
本聯盟計分指標：
  打擊：{", ".join(BATTING_CATS)}
  投球：{", ".join(PITCHING_CATS)}

我的目前陣容：
{json.dumps(roster, ensure_ascii=False, indent=2)}

可撿的自由球員：
{json.dumps(fa, ensure_ascii=False, indent=2)}

請根據今日賽程與球員近況，給出 {config["claude"]["max_words"]} 字以內的建議：
1. 今日最佳首發配置（依上述打擊/投球指標）。
2. 建議撿起哪位自由球員並丟掉誰，對哪些指標有幫助。
3. 本週勝率評估。

請用繁體中文回答。
"""

    response = client.messages.create(
        model=config["claude"]["model"],
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    advice = response.content[0].text
    logger.info("Claude 分析完成")

    # 4. 寫入 Google Sheets（選填）
    today = str(date.today())
    write_to_google_sheets(today, roster, fa, advice)

    # 5. LINE 推播
    configuration = Configuration(access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
    with ApiClient(configuration) as api_client:
        line_bot = MessagingApi(api_client)
        line_bot.push_message(
            PushMessageRequest(
                to=os.environ.get("LINE_USER_ID"),
                messages=[LineTextMessage(text=f"⚾ Fantasy 每日戰報 {today}：\n\n{advice}")],
            )
        )
    logger.info("LINE 推播完成")


if __name__ == "__main__":
    run_fantasy_advisor()
