#!/usr/bin/env python3
import os
import random
import shutil
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

from config.settings import GECKODRIVER_LOG

SITES = [
    "https://www.google.com",
    "https://github.com",
    "https://www.wikipedia.org",
    "https://ubuntu.com",
    "https://www.debian.org",
    "https://www.python.org",
    "https://developer.mozilla.org",
    "https://news.ycombinator.com",
    "https://www.cloudflare.com",
    "https://www.mozilla.org",
]

DURATION = 600


def safe_get(driver, url):
    try:
        driver.get(url)
    except Exception:
        pass


def safe_scroll(driver):
    try:
        for _ in range(random.randint(2, 5)):
            y = random.randint(300, 1200)
            driver.execute_script(f"window.scrollBy(0, {y});")
            time.sleep(random.uniform(0.5, 1.5))
    except Exception:
        pass


def safe_click_some_links(driver):
    try:
        links = driver.find_elements(By.TAG_NAME, "a")
        random.shuffle(links)
        for link in links[:5]:
            href = link.get_attribute("href")
            if href and href.startswith("http"):
                driver.execute_script("window.open(arguments[0], '_blank');", href)
                time.sleep(random.uniform(1, 2))
                return
    except Exception:
        pass


def main():
    geckodriver_path = shutil.which("geckodriver")
    firefox_path = shutil.which("firefox")

    if not geckodriver_path:
        raise RuntimeError("geckodriver introuvable dans le PATH")
    if not firefox_path:
        raise RuntimeError("firefox introuvable dans le PATH")

    profile_root = os.path.expanduser("~/tmp/geckodriver-profiles")
    os.makedirs(profile_root, exist_ok=True)
    GECKODRIVER_LOG.parent.mkdir(parents=True, exist_ok=True)

    options = Options()
    options.binary_location = firefox_path

    service = Service(
        executable_path=geckodriver_path,
        service_args=[f"--profile-root={profile_root}"],
        env={**os.environ, "TMPDIR": profile_root},
        log_output=str(GECKODRIVER_LOG),
    )

    driver = webdriver.Firefox(service=service, options=options)
    driver.set_page_load_timeout(20)

    end = time.time() + DURATION

    try:
        while time.time() < end:
            batch = random.sample(SITES, k=random.randint(2, 4))
            safe_get(driver, batch[0])
            time.sleep(random.uniform(2, 4))
            safe_scroll(driver)

            for url in batch[1:]:
                try:
                    driver.execute_script("window.open(arguments[0], '_blank');", url)
                    time.sleep(random.uniform(1, 3))
                except Exception:
                    pass

            handles = driver.window_handles[:]
            for handle in handles:
                try:
                    driver.switch_to.window(handle)
                    time.sleep(random.uniform(2, 4))
                    safe_scroll(driver)
                    if random.random() < 0.33:
                        safe_click_some_links(driver)
                except Exception:
                    pass

            handles = driver.window_handles[:]
            while len(handles) > 5:
                try:
                    driver.switch_to.window(handles[-1])
                    driver.close()
                except Exception:
                    pass
                handles = driver.window_handles[:]

            if driver.window_handles:
                driver.switch_to.window(driver.window_handles[0])

            time.sleep(random.uniform(2, 5))

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
