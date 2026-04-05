"""
CULKO Automation API Server — Async Fire-and-Poll Architecture
Sessions are managed in-memory. No filesystem IPC needed.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict
import uuid
import time
import base64
import threading

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

app = FastAPI(title="CULKO Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================
# In-memory session store
# =====================================================
sessions: Dict[str, dict] = {}
sessions_lock = threading.Lock()

def get_session(session_id: str) -> Optional[dict]:
    with sessions_lock:
        return sessions.get(session_id)

def set_session(session_id: str, data: dict):
    with sessions_lock:
        sessions[session_id] = data

def update_session(session_id: str, **kwargs):
    with sessions_lock:
        if session_id in sessions:
            sessions[session_id].update(kwargs)

def delete_session(session_id: str):
    with sessions_lock:
        sess = sessions.pop(session_id, None)
    if sess:
        driver = sess.get('driver')
        if driver:
            try: driver.quit()
            except: pass

# =====================================================
# Chrome Driver Setup
# =====================================================
def create_driver():
    opts = Options()
    opts.page_load_strategy = 'eager'
    opts.add_argument('--headless')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)

    try:
        # First try system chromedriver (Render/Docker environments)
        service = Service('/usr/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=opts)
    except Exception:
        # Fallback: let selenium find it
        driver = webdriver.Chrome(options=opts)

    try:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    except: pass
    
    return driver

# =====================================================
# Background Login Task: Navigate to CAPTCHA
# =====================================================
def bg_navigate_to_captcha(session_id: str, uid: str, password: str):
    driver = None
    try:
        driver = create_driver()
        update_session(session_id, driver=driver, status='navigating')

        driver.get('https://student.culko.in/Login.aspx')
        wait = WebDriverWait(driver, 25)

        # Step 1: Enter UID
        uid_field = wait.until(EC.presence_of_element_located((By.ID, 'txtUserId')))
        uid_field.clear()
        uid_field.send_keys(uid)

        # Step 2: Click Next
        next_btn = wait.until(EC.element_to_be_clickable((By.ID, 'btnNext')))
        next_btn.click()

        # Step 3: Wait for password field
        time.sleep(0.5) # Short wait for animation/transition
        WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="password"]'))
        )

        # Step 4: Grab CAPTCHA image
        captcha_img = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, 'imgCaptcha'))
        )
        screenshot_bytes = captcha_img.screenshot_as_png
        b64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        update_session(session_id,
            status='captcha_ready',
            captcha_b64=b64,
            password=password,
        )

    except Exception as e:
        print(f"[{session_id}] Navigation error: {e}", flush=True)
        if driver:
            try: driver.quit()
            except: pass
        update_session(session_id, status='error', error=str(e))

# =====================================================
# Background Login Task: Submit CAPTCHA
# =====================================================
def bg_submit_captcha(session_id: str):
    sess = get_session(session_id)
    if not sess:
        return

    driver = sess.get('driver')
    password = sess.get('password', '')
    captcha_text = sess.get('captcha_text', '')

    try:
        # Enter password
        pass_input = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
        pass_input.clear()
        pass_input.send_keys(password)

        # Enter CAPTCHA
        captcha_input = driver.find_element(By.ID, 'txtcaptcha')
        captcha_input.clear()
        captcha_input.send_keys(captcha_text)

        # Submit
        submit_btn = driver.find_element(By.ID, 'btnLogin')
        submit_btn.click()

        time.sleep(4)

        # Collect cookies
        raw_cookies = driver.get_cookies()
        cookies = {c['name']: c['value'] for c in raw_cookies}

        try: driver.quit()
        except: pass

        update_session(session_id, status='done', cookies=cookies, driver=None)
        print(f"[{session_id}] Login complete, {len(cookies)} cookies set.", flush=True)

    except Exception as e:
        print(f"[{session_id}] Submit error: {e}", flush=True)
        if driver:
            try: driver.quit()
            except: pass
        update_session(session_id, status='error', error=str(e), driver=None)

# =====================================================
# Models
# =====================================================
class InitRequest(BaseModel):
    uid: str
    password: str

class SubmitRequest(BaseModel):
    sessionId: str
    captchaText: str

# =====================================================
# Routes
# =====================================================

@app.get("/health")
def health():
    return {"status": "healthy", "active_sessions": len(sessions)}

@app.post("/api/interactive/init")
def interactive_init(request: InitRequest):
    """
    Starts the browser session in the background.
    Returns immediately with a sessionId — the client must poll /status.
    """
    session_id = str(uuid.uuid4())
    set_session(session_id, {
        'status': 'starting',
        'driver': None,
        'captcha_b64': None,
        'password': request.password,
        'captcha_text': None,
        'cookies': None,
        'error': None,
        'created_at': time.time(),
    })

    t = threading.Thread(
        target=bg_navigate_to_captcha,
        args=(session_id, request.uid, request.password),
        daemon=True
    )
    t.start()

    print(f"[{session_id}] Session started for UID: {request.uid}", flush=True)
    return {"success": True, "sessionId": session_id, "status": "starting"}

@app.get("/api/interactive/status/{session_id}")
def interactive_status(session_id: str):
    """
    Poll this endpoint every 2 seconds.
    Returns current status: starting | navigating | captcha_ready | submitting | done | error
    """
    sess = get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    status = sess.get('status')

    if status == 'captcha_ready':
        return {
            "status": "captcha_ready",
            "captchaImage": f"data:image/png;base64,{sess['captcha_b64']}"
        }
    elif status == 'done':
        cookies = sess.get('cookies', {})
        delete_session(session_id)
        return {"status": "done", "cookies": cookies}
    elif status == 'error':
        error = sess.get('error', 'Unknown error')
        delete_session(session_id)
        return {"status": "error", "error": error}
    else:
        return {"status": status}

@app.post("/api/interactive/submit")
def interactive_submit(request: SubmitRequest):
    """
    Submit the CAPTCHA text. Fires the browser submission in background.
    Client should then poll /status for 'done' or 'error'.
    """
    sess = get_session(request.sessionId)
    if not sess or sess.get('status') != 'captcha_ready':
        raise HTTPException(status_code=400, detail="Session not ready or expired")

    update_session(request.sessionId,
        status='submitting',
        captcha_text=request.captchaText
    )

    t = threading.Thread(
        target=bg_submit_captcha,
        args=(request.sessionId,),
        daemon=True
    )
    t.start()

    return {"success": True, "status": "submitting"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
