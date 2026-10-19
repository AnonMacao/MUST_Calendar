from __future__ import annotations

import os
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expected
from selenium.webdriver.support.ui import WebDriverWait


LOGIN_URL = "https://login.must.edu.mo/login"
LOGIN_TIMEOUT_SECONDS = 30
PAGE_LOAD_TIMEOUT_SECONDS = 45


class Login:
    def __init__(self, username: str, password: str):
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--no-proxy-server")

        driver_path = os.environ.get("CHROMEDRIVER_PATH")
        service = (
            Service(executable_path=str(Path(driver_path).resolve()))
            if driver_path
            else Service()
        )
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
        self.wait = WebDriverWait(self.driver, LOGIN_TIMEOUT_SECONDS)
        self.username = username
        self.password = password
        try:
            self._login()
        except Exception:
            self.driver.quit()
            raise

    def _login(self) -> None:
        self.driver.get(LOGIN_URL)
        account = self.wait.until(
            expected.presence_of_element_located((By.ID, "username"))
        )
        account_password = self.driver.find_element(By.ID, "password")
        submit = self.driver.find_element(By.ID, "submitButton")
        privacy_policy = self.driver.find_element(By.ID, "checkboxByPrivacyPolicy")

        account.send_keys(self.username)
        account_password.send_keys(self.password)
        if not privacy_policy.is_selected():
            privacy_policy.click()

        login_page_url = self.driver.current_url
        submit.click()
        try:
            self.wait.until(
                lambda driver: driver.current_url != login_page_url
                or not driver.find_elements(By.ID, "submitButton")
            )
        except TimeoutException as error:
            raise RuntimeError(
                "MUST login failed; check the account credentials"
            ) from error

    def get_site_cookie(self, site_url: str, cookie_name: str) -> str:
        self.driver.get(site_url)
        try:
            cookie = self.wait.until(lambda driver: driver.get_cookie(cookie_name))
        except TimeoutException as error:
            raise RuntimeError(
                f"MUST login did not create the required {cookie_name} session"
            ) from error
        return str(cookie["value"])

    def close(self) -> None:
        self.driver.quit()
