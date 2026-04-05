from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict
import sys
import os
import uuid
import asyncio
import time
import json
import base64

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import threading

app = FastAPI(title="CULKO Automation API")

class InitRequest(BaseModel):
    uid: str
    password: str

class SubmitRequest(BaseModel):
    sessionId: str
    captchaText: str

class SessionManager:
    def __init__(self):
        self.sessions = {}

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def set_session(self, session_id, data):
        self.sessions[session_id] = data
        
    def delete_session(self, session_id):
        if session_id in self.sessions:
            driver = self.sessions[session_id].get('driver')
            try:
                if driver: driver.quit()
            except: pass
            del self.sessions[session_id]

session_manager = SessionManager()

from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

def driver_setup():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Hide automation flags
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {
        "userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

def run_login_until_captcha(session_id, uid, password):
    driver = None
    try:
        driver = driver_setup()
        session_manager.set_session(session_id, {'driver': driver, 'status': 'navigating', 'event': threading.Event(), 'captcha_text': None, 'cookies': None, 'error': None})
        
        driver.get('https://student.culko.in/Login.aspx')
        wait = WebDriverWait(driver, 20)
        
        uid_input = wait.until(EC.presence_of_element_located((By.ID, 'txtUserId')))
        uid_input.clear()
        uid_input.send_keys(uid)
        
        next_btn = wait.until(EC.element_to_be_clickable((By.ID, 'btnNext')))
        next_btn.click()
        
        # Wait password
        time.sleep(3)
        pass_input = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="password"]')))
        
        captcha_img = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'imgCaptcha')))
        screenshot_bytes = captcha_img.screenshot_as_png
        b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        session_data = session_manager.get_session(session_id)
        session_data['status'] = 'captcha_ready'
        session_data['b64'] = b64
        session_data['password'] = password
        
    except Exception as e:
        if driver: driver.quit()
        session_data = session_manager.get_session(session_id)
        if session_data:
            session_data['status'] = 'error'
            session_data['error'] = str(e)

def run_login_submission(session_id):
    session_data = session_manager.get_session(session_id)
    driver = session_data['driver']
    password = session_data['password']
    captcha_text = session_data['captcha_text']
    
    try:
        wait = WebDriverWait(driver, 20)
        # Enter password
        pass_input = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
        pass_input.clear()
        pass_input.send_keys(password)
        
        captcha_input = driver.find_element(By.ID, 'txtcaptcha')
        captcha_input.clear()
        captcha_input.send_keys(captcha_text)
        
        submit_btn = driver.find_element(By.ID, 'btnSubmit')
        submit_btn.click()
        
        time.sleep(4)
        
        cookies = {}
        for cookie in driver.get_cookies():
            cookies[cookie['name']] = cookie['value']
            
        session_data['status'] = 'done'
        session_data['cookies'] = cookies
        driver.quit()
    except Exception as e:
        if driver: driver.quit()
        session_data['status'] = 'error'
        session_data['error'] = str(e)

@app.post("/api/interactive/init")
async def interactive_init(request: InitRequest, background_tasks: BackgroundTasks):
    session_id = str(uuid.uuid4())
    
    # Run the selenium tasks in a background thread to bypass asyncio blocking
    thread = threading.Thread(target=run_login_until_captcha, args=(session_id, request.uid, request.password))
    thread.start()
    
    attempts = 0
    while attempts < 30: # 30 seconds wait for navigation
        await asyncio.sleep(1)
        session_data = session_manager.get_session(session_id)
        
        if not session_data: continue
            
        if session_data['status'] == 'captcha_ready':
            return {
                "success": True,
                "requireCaptcha": True,
                "sessionId": session_id,
                "captchaImage": f"data:image/png;base64,{session_data['b64']}"
            }
        elif session_data['status'] == 'error':
            return {"success": False, "error": session_data['error']}
            
        attempts += 1
        
    session_manager.delete_session(session_id)
    raise HTTPException(status_code=504, detail="Timeout navigating to portal")

@app.post("/api/interactive/submit")
async def interactive_submit(request: SubmitRequest):
    session_id = request.sessionId
    session_data = session_manager.get_session(session_id)
    
    if not session_data or session_data['status'] != 'captcha_ready':
        raise HTTPException(status_code=400, detail="Invalid or expired session")
        
    session_data['captcha_text'] = request.captchaText
    session_data['status'] = 'submitting'
    
    thread = threading.Thread(target=run_login_submission, args=(session_id,))
    thread.start()
    
    attempts = 0
    while attempts < 30: # 30 secs to login
        await asyncio.sleep(1)
        session_data = session_manager.get_session(session_id)
        
        if session_data['status'] == 'done':
            cookies = session_data['cookies']
            session_manager.delete_session(session_id)
            return {"success": True, "cookies": cookies}
        elif session_data['status'] == 'error':
            error_msg = session_data['error']
            session_manager.delete_session(session_id)
            return {"success": False, "error": error_msg}
            
        attempts += 1
        
    session_manager.delete_session(session_id)
    raise HTTPException(status_code=504, detail="Timeout logging in")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
