import os
from urllib.parse import quote
from bs4 import BeautifulSoup
import re
import html as html_lib
from datetime import date, timedelta
import asyncio
import aiohttp
from tqdm.asyncio import tqdm_asyncio

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")
CALENDAR_ID = "pmi414.rea@gmail.com"
TIMEZONE = "Europe/Amsterdam"

TOKEN_URL = "https://oauth2.googleapis.com/token"
BASE_URL = "https://www.googleapis.com/calendar/v3"

referer_value = "https://rasp.rea.ru/?q=" + quote("15.27д-пм04/22б")
url = "https://rasp.rea.ru/Schedule/GetDetails"

headers = {
    "Accept": "text/html, */*; q=0.01",
    "Referer": referer_value,
    "Sec-Ch-Ua": '"Not)A;Brand";v="8", "Chromium";v="138", "YaBrowser";v="25.8", "Yowser";v="2.5"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/138.0.0.0 YaBrowser/25.8.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
}

PAIR_TIME = {
    '1 пара': ('08:30', '10:00'),
    '2 пара': ('10:10', '11:40'),
    '3 пара': ('11:50', '13:20'),
    '4 пара': ('14:00', '15:30'),
    '5 пара': ('15:40', '17:10'),
    '6 пара': ('17:20', '18:50'),
}
RU_MONTHS = {
    "января": "01", "февраля": "02", "марта": "03", "апреля": "04", "мая": "05", "июня": "06",
    "июля": "07", "августа": "08", "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12",
}

selection = "15.27д-пм04/22б"


def to_iso_date(date_ru: str) -> str:
    d, m_ru, y = date_ru.split()
    return f"{y}-{RU_MONTHS[m_ru]}-{int(d):02d}"


def html_to_google_event(html: str, tz: str = "Europe/Moscow") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n", strip=True)

    # summary
    h5 = soup.find("h5")
    summary = html_lib.unescape(h5.get_text(strip=True)) if h5 else None

    # дата и пара
    m = re.search(
        r"(?:понедельник|вторник|среда|четверг|пятница|суббота|воскресенье),\s*"
        r"(\d{2}\s+[а-яё]+\s+\d{4}),\s*([1-6])\s*пара",
        text, re.IGNORECASE
    )
    date_ru, pair_num = (m.group(1), m.group(2)) if m else (None, None)
    pair_label = f"{pair_num} пара" if pair_num else None
    start_time, end_time = PAIR_TIME.get(pair_label, (None, None))

    # аудитория
    aud = None
    m = re.search(r"Аудитория:\s*([\s\S]*?)<br", html, re.IGNORECASE)
    if m:
        aud = re.sub(r"\s+", " ", html_lib.unescape(m.group(1))).strip(" -").strip("*")

    # тип занятия
    kind = None
    strong = soup.find("strong")
    if strong:
        kind = strong.get_text(strip=True)

    # преподаватель
    teacher = None
    m = re.search(r"</i>\s*([^<]+)</a>", html)
    if m:
        teacher = html_lib.unescape(m.group(1)).strip()

    color_id = "6"  # по умолчанию красный
    if kind:
        if "лекция" in kind.lower():
            color_id = "2"
        elif "практичес" in kind.lower():
            color_id = "7"
        elif "лаборатор" in kind.lower():
            color_id = "9"

    description = ", ".join([p for p in (kind, aud, teacher) if p])

    iso_date = to_iso_date(date_ru) if date_ru else None

    return {
        "summary": summary,
        "description": description or None,
        "start": {"dateTime": f"{iso_date}T{start_time}:00", "timeZone": tz},
        "end": {"dateTime": f"{iso_date}T{end_time}:00", "timeZone": tz},
        "colorId": color_id,
    }


results = []


async def fetch_one(session, url: str, headers: dict, payload: dict):
    async with session.get(url, headers=headers, params=payload) as resp:
        resp.raise_for_status()
        return await resp.text()


async def fetch_all(url, headers, payloads, concurrency: int = 10):
    results = []
    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession() as session:
        async def run_one(payload):
            async with sem:
                html = await fetch_one(session, url, headers, payload)
                event = html_to_google_event(html)  # sync обработка
                if event.get("summary"):
                    results.append(event)

        tasks = [run_one(p) for p in payloads]
        for f in tqdm_asyncio.as_completed(tasks, desc="Shooting responses"):
            await f

    return results


async def get_access_token(session: aiohttp.ClientSession) -> str:
    """Меняем refresh_token на access_token (OAuth 2.0, без браузера)."""
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
    }
    async with session.post(TOKEN_URL, data=data, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        resp.raise_for_status()
        js = await resp.json()
        return js["access_token"]


async def insert_event(session: aiohttp.ClientSession, access_token: str, event, send_updates: str = "none"):
    """POST /calendars/{id}/events — создать событие."""
    url = f"{BASE_URL}/calendars/{CALENDAR_ID}/events"
    params = {"sendUpdates": send_updates, "supportsAttachments": "true"}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    async def _post(hdrs):
        async with session.post(
                url, headers=hdrs, params=params, json=event, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status == 401:
                return resp.status, None
            resp.raise_for_status()
            return resp.status, await resp.json()

    # первый запрос
    status, data = await _post(headers)
    if status == 401:
        # Просрочился access_token — обновим и повторим один раз
        new_token = await get_access_token(session)
        headers["Authorization"] = f"Bearer {new_token}"
        status, data = await _post(headers)
    # если второй раз вернётся не-200, .raise_for_status() уже бросит исключение в _post
    return data


# ==== Главная корутина ====
async def main():
    start_date = date(2025, 9, 2)
    end_date = date(2025, 12, 31)

    payloads: list[dict] = []
    current = start_date
    while current <= end_date:
        for slot in range(1, 7):
            payloads.append({
                "selection": selection,
                "date": current.strftime("%d.%m.%Y"),
                "timeSlot": str(slot),
            })
        current += timedelta(days=1)

    print(f"Собрано payloads: {len(payloads)}")

    # 2) Тянем HTML и превращаем в события
    events = await fetch_all(url, headers, payloads, concurrency=10)
    print(f"Событий к созданию: {len(events)}")

    if not events:
        print("Нет валидных событий для создания — выходим.")
        return

    # 3) Создаём события в Google Calendar
    async with aiohttp.ClientSession() as session:
        token = await get_access_token(session)
        for i, ev in enumerate(events, 1):
            try:
                created = await insert_event(session, token, ev)
                print(f"[{i}/{len(events)}] {created.get('summary')} → id={created.get('id')}")
            except Exception as e:
                print(f"[{i}/{len(events)}] Ошибка при создании события '{ev.get('summary')}': {e}")


# Точка входа
if __name__ == "__main__":
    asyncio.run(main())
