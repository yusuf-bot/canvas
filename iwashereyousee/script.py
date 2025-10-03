import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import time

# Load .env
load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
TO_NUMBER = os.getenv("TO_NUMBER")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")

EXTRACT_FILE = "extract.json"
BASE_URL = "https://iwashereyousee.blogspot.com"

# Load existing JSON data
if os.path.exists(EXTRACT_FILE):
    with open(EXTRACT_FILE, "r") as f:
        data = json.load(f)
else:
    data = []

def save_json():
    with open(EXTRACT_FILE, "w") as f:
        json.dump(data, f, indent=4)


def fetch_archive_posts(year, month):
    """Return list of posts with title, href, and publish_time"""
    url = f"{BASE_URL}/{year}/{str(month).zfill(2)}"
    r = requests.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    posts = []

    for h3 in soup.find_all("h3", class_="post-title entry-title"):
        a = h3.find("a")
        if a:
            href = a["href"]
            title = a.text.strip()
            # Attempt to get time from archive page
            parent_post = h3.parent
            time_elem = parent_post.find("time", class_="published") if parent_post else None
            if time_elem:
                publish_time = time_elem["datetime"]
            else:
                publish_time = None  # will fetch later from post page
            posts.append({
                "title": title,
                "href": href,
                "publish_time": publish_time
            })
    # Sort posts by datetime (oldest first)
    for post in posts:
        if post["publish_time"]:
            post["publish_time_obj"] = datetime.fromisoformat(post["publish_time"].replace("Z","+00:00"))
        else:
            post["publish_time_obj"] = datetime.min
    posts.sort(key=lambda x: x["publish_time_obj"])
    return posts

def fetch_post_content(url):
    r = requests.get(url)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    body_div = soup.find("div", class_="post-body-container")

    if body_div:
        # Extract visible text in order, keep paragraphs/line breaks
        content_text = body_div.get_text(separator="\n", strip=True)
    else:
        content_text = ""

    time_elem = soup.find("time", class_="published")
    publish_time = time_elem["datetime"] if time_elem else ""
    return content_text, publish_time



def send_email(subject, html_content):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(html_content, "html"))

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(EMAIL_USER, EMAIL_PASS)
    server.send_message(msg)
    server.quit()
    print("Email sent")

def main():
    start_year = 2022
    start_month = 1
    now = datetime.now()
    end_year = now.year
    end_month = now.month

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            if year == end_year and month > end_month:
                break
            print(f"Scraping {year}-{str(month).zfill(2)}...")
            try:
                posts = fetch_archive_posts(year, month)
            except Exception as e:
                print(f"Failed to fetch {year}-{month}: {e}")
                continue

            for post in posts:
                title = post["title"]
                href = post["href"]
                if any(post['title'] == title for post in data):
                    continue  # already processed
                try:
                    content_html, publish_time = fetch_post_content(href)
                    if not post["publish_time"]:
                        post["publish_time"] = publish_time
                except Exception as e:
                    print(f"Failed to fetch post {href}: {e}")
                    continue

                data.append({
                    "title": title,
                    "href": href,
                    "extract": content_text,
                    "time": publish_time
                })

                save_json()
                send_email(title, content_html)
                time.sleep(1)  # small delay

if __name__ == "__main__":
    main()
