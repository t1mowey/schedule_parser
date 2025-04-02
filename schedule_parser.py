import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time
import re

chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
url = "https://rasp.rea.ru/?q=15.27д-пм04%2F22б"
driver.get(url)
time.sleep(2)

try:
    next_button = driver.find_element(By.XPATH, "//button[@id='next']")
    next_button.click()
    time.sleep(3)
    next_button.click()
    time.sleep(3)
except Exception as e:
    print("Ошибка при нажатии на кнопку:", e)

pair_time = {
    '1 пара': ('08:30', '10:00'),
    '2 пара': ('10:10', '11:40'),
    '3 пара': ('11:50', '13:20'),
    '4 пара': ('14:00', '15:30'),
    '5 пара': ('15:40', '17:10'),
    '6 пара': ('17:20', '18:50')
}

lessons = driver.find_elements(By.XPATH, "//a[contains(@class, 'task')]")
data = []

for lesson in lessons:
    try:
        driver.execute_script("arguments[0].click();", lesson)
        time.sleep(3)

        modal_body = driver.find_element(By.CLASS_NAME, "element-info-body").text

        subject_match = re.search(r"^(.*?)\n", modal_body)
        typ_match = re.search(r"\n(.*?)\nID:", modal_body)
        date_match = re.search(r"(\w+), (\d+ \w+ \d{4}), (\d+) пара", modal_body)
        cabinet_match = re.search(r"Аудитория: (.+)", modal_body)
        teacher_match = re.search(r"Преподаватель:\s*\n?.*? (\w+ \w+ \w+)", modal_body)

        subject = subject_match.group(1) if subject_match else "Не найдено"
        typ = typ_match.group(1) if typ_match else "Не найдено"
        date = date_match.group(2) if date_match else "Не найдено"
        pair_num = date_match.group(3) + ' пара' if date_match else "Не найдено"
        cabinet = cabinet_match.group(1) if cabinet_match else "Не найдено"
        teacher = teacher_match.group(1) if teacher_match else "Не найдено"

        months = {
            "января": "01", "февраля": "02", "марта": "03", "апреля": "04",
            "мая": "05", "июня": "06", "июля": "07", "августа": "08",
            "сентября": "09", "октября": "10", "ноября": "11", "декабря": "12"
        }

        day, month_word, year = date.split()
        date_iso = f"{year}-{months[month_word]}-{day.zfill(2)}"

        start_time = pair_time[pair_num][0]
        end_time = pair_time[pair_num][1]

        start_datetime = f"{date_iso}T{start_time}:00"
        end_datetime = f"{date_iso}T{end_time}:00"

        if "Лекция" in typ:
            color = 5  
        elif "Практическое занятие" in typ:
            color = 6  
        else:
            color = 3  

        data.append({
            'Subject': f'{subject}',
            'Start DateTime': start_datetime,
            'End DateTime': end_datetime,
            'Description': f'{typ}, {cabinet}, {teacher}',
            'Location': '',
            'Color': color 
        })


    except Exception as e:
        print(f"Ошибка при открытии пары: {e}")
    try:
        close_button = driver.find_element(By.XPATH, "//button[@data-dismiss='modal']")
        driver.execute_script("arguments[0].click();", close_button)
        time.sleep(3)
    except Exception as e:
        print(f"Ошибка при закрытии пары: {e}")

df = pd.DataFrame(data).drop_duplicates()
print(df)
df.to_csv('planer.csv', index=False)
driver.quit()
