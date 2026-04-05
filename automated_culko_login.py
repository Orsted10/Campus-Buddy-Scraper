"""
Automated CULKO Login with CAPTCHA Solving
Uses Selenium for browser automation and Tesseract OCR for CAPTCHA recognition
"""

import os
import sys
import time
import json
import base64
from io import BytesIO
from PIL import Image
import pytesseract
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from typing import Dict, Optional

class CULKOCaptchaSolver:
    """Handles CAPTCHA detection and solving for CULKO portal"""
    
    def __init__(self):
        self.driver = None
        
    def setup_driver(self, headless: bool = True) -> webdriver.Chrome:
        """Setup Chrome driver with optimal settings"""
        chrome_options = Options()
        
        if headless:
            chrome_options.add_argument('--headless')
        
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Disable automation detection
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Execute CDP commands to avoid detection
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            '''
        })
        
        return self.driver
    
    def solve_captcha(self, captcha_element) -> str:
        """Solve CAPTCHA using OCR with image preprocessing"""
        try:
            # Get CAPTCHA image
            captcha_screenshot = captcha_element.screenshot_as_png
            
            # Open with PIL
            image = Image.open(BytesIO(captcha_screenshot))
            
            # Preprocess image for better OCR
            # Convert to grayscale
            image = image.convert('L')
            
            # Increase contrast
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)
            
            # Apply threshold to make it binary (black and white)
            image = image.point(lambda x: 0 if x < 128 else 255, '1')
            
            # Resize for better OCR
            image = image.resize((image.width * 3, image.height * 3), Image.LANCZOS)
            
            # Try to use Tesseract OCR
            try:
                # Use Tesseract OCR with specific configuration for alphanumeric
                custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
                captcha_text = pytesseract.image_to_string(image, config=custom_config).strip()
                
                # Clean up the result
                captcha_text = ''.join(captcha_text.split())  # Remove all whitespace
                
                print(f"Solved CAPTCHA: {captcha_text}", file=sys.stderr)
                return captcha_text
            except Exception as tesseract_error:
                print(f"Tesseract not available: {tesseract_error}", file=sys.stderr)
                print("Please install Tesseract OCR for better CAPTCHA solving", file=sys.stderr)
                print("For now, returning empty string - manual intervention needed", file=sys.stderr)
                return ""
            
        except Exception as e:
            print(f"Error solving CAPTCHA: {e}", file=sys.stderr)
            return ""
    
    def login_with_credentials(self, uid: str, password: str, headless: bool = True, manual_captcha: bool = False, interactive_api: bool = False, session_id: str = None) -> Optional[Dict]:
        """
        Automated login to CULKO portal with CAPTCHA solving
        
        Args:
            uid: Student UID
            password: Student password
            headless: Run browser in headless mode
            manual_captcha: If True, pause for user to enter CAPTCHA manually
            interactive_api: If True, use file-based IPC to pause and wait for CAPTCHA input
            session_id: The session ID for the interactive API files
            
        Returns:
            Dictionary containing session cookies or None if failed
        """
        driver = None
        try:
            print("Setting up browser...", file=sys.stderr)
            driver = self.setup_driver(headless=headless)
            wait = WebDriverWait(driver, 20)
            
            # Step 1: Navigate to login page
            print("Navigating to login page...", file=sys.stderr)
            driver.get('https://student.culko.in/Login.aspx')
            time.sleep(2)
            
            # Step 2: Enter UID and click NEXT
            print("Entering UID...", file=sys.stderr)
            uid_input = wait.until(EC.presence_of_element_located((By.ID, 'txtUserId')))
            uid_input.clear()
            uid_input.send_keys(uid)
            
            # Try multiple selectors for the NEXT button
            next_button = None
            for selector in [(By.ID, 'btnNext'), (By.NAME, 'btnNext'), (By.CSS_SELECTOR, 'input[type="submit"]')]:
                try:
                    next_button = driver.find_element(*selector)
                    break
                except:
                    continue
            
            if next_button:
                next_button.click()
                print("NEXT button clicked, waiting for password page...", file=sys.stderr)
            else:
                print("Could not find NEXT button", file=sys.stderr)
                return None
                
            # Wait longer and try multiple approaches to detect password page
            time.sleep(5)
            
            # Try to find password input with longer timeout and multiple selectors
            print("Looking for password field...", file=sys.stderr)
            password_input = None
            
            # Save screenshot for debugging
            try:
                driver.save_screenshot('debug_after_next.png')
                print("Screenshot saved to debug_after_next.png", file=sys.stderr)
            except:
                pass
            
            # Try multiple selectors for password field
            for selector in [(By.ID, 'txtPassword'), (By.NAME, 'txtPassword'), (By.CSS_SELECTOR, 'input[type="password"]')]:
                try:
                    wait_password = WebDriverWait(driver, 30)  # Increased timeout
                    password_input = wait_password.until(EC.presence_of_element_located(selector))
                    print(f"Found password field using {selector}", file=sys.stderr)
                    break
                except:
                    print(f"Selector {selector} not found, trying next...", file=sys.stderr)
                    continue
            
            if not password_input:
                print("ERROR: Could not find password field after clicking NEXT", file=sys.stderr)
                print(f"Current URL: {driver.current_url}", file=sys.stderr)
                
                # Try to get page source for debugging
                try:
                    with open('debug_page_source.html', 'w', encoding='utf-8') as f:
                        f.write(driver.page_source)
                    print("Page source saved to debug_page_source.html", file=sys.stderr)
                except:
                    pass
                
                return None
            
            # Step 4: Solve CAPTCHA or ask user
            print("Handling CAPTCHA...", file=sys.stderr)
            max_retries = 3
            captcha_solved = False
            
            for attempt in range(max_retries):
                try:
                    # Find CAPTCHA image
                    captcha_img = wait.until(EC.presence_of_element_located((By.ID, 'imgCaptcha')))
                    
                    if interactive_api and session_id:
                        # Interactive Web API Mode (File-based IPC)
                        print(f"Saving CAPTCHA image for session {session_id}...", file=sys.stderr)
                        captcha_screenshot = captcha_img.screenshot_as_png
                        
                        os.makedirs('.sessions', exist_ok=True)
                        captcha_path = f".sessions/{session_id}_captcha.png"
                        with open(captcha_path, "wb") as f:
                            f.write(captcha_screenshot)
                            
                        status_path = f".sessions/{session_id}_status.json"
                        with open(status_path, "w") as f:
                            json.dump({"status": "waiting_captcha"}, f)
                            
                        print(f"Status written. Waiting for Next.js to provide CAPTCHA text in .sessions/{session_id}_input.txt...", file=sys.stderr)
                        input_path = f".sessions/{session_id}_input.txt"
                        
                        wait_time = 0
                        captcha_text = ""
                        while wait_time < 300: # 5 minute timeout
                            if os.path.exists(input_path):
                                try:
                                    with open(input_path, "r") as f:
                                        captcha_text = f.read().strip()
                                    if captcha_text:
                                        os.remove(input_path)  # Clean up once read
                                        break
                                except Exception as err:
                                    print(f"Error reading input file: {err}", file=sys.stderr)
                            time.sleep(1)
                            wait_time += 1
                            
                        if captcha_text:
                            # Enter CAPTCHA
                            captcha_input = driver.find_element(By.ID, 'txtcaptcha')
                            captcha_input.clear()
                            captcha_input.send_keys(captcha_text)
                            captcha_solved = True
                            print(f"CAPTCHA entered via interactive API: {captcha_text}", file=sys.stderr)
                            
                            # Clean up the status file and image
                            try:
                                if os.path.exists(status_path): os.remove(status_path)
                                if os.path.exists(captcha_path): os.remove(captcha_path)
                            except: pass
                            
                            break
                        else:
                            print("Timeout waiting for CAPTCHA input via file", file=sys.stderr)
                            return None

                    elif manual_captcha or not pytesseract:
                        # Manual CAPTCHA entry mode
                        print("\n" + "="*60, file=sys.stderr)
                        print("CAPTCHA MANUAL ENTRY MODE", file=sys.stderr)
                        print("="*60, file=sys.stderr)
                        print("A browser window will open showing the CAPTCHA.", file=sys.stderr)
                        print("Please look at the browser and enter the CAPTCHA text below.", file=sys.stderr)
                        print("="*60 + "\n", file=sys.stderr)
                        
                        captcha_text = input("Enter CAPTCHA from browser: ").strip()
                        
                        if captcha_text:
                            # Enter CAPTCHA
                            captcha_input = driver.find_element(By.ID, 'txtcaptcha')
                            captcha_input.clear()
                            captcha_input.send_keys(captcha_text)
                            captcha_solved = True
                            print(f"CAPTCHA entered manually: {captcha_text}", file=sys.stderr)
                            break
                        else:
                            print("Empty CAPTCHA, please try again", file=sys.stderr)
                    else:
                        # Automatic CAPTCHA solving with Tesseract
                        captcha_text = self.solve_captcha(captcha_img)
                        
                        if len(captcha_text) >= 4:  # Minimum reasonable length
                            # Enter CAPTCHA
                            captcha_input = driver.find_element(By.ID, 'txtcaptcha')
                            captcha_input.clear()
                            captcha_input.send_keys(captcha_text)
                            captcha_solved = True
                            print(f"CAPTCHA entered automatically: {captcha_text}", file=sys.stderr)
                            break
                        else:
                            print(f"CAPTCHA too short ({len(captcha_text)} chars), retrying...", file=sys.stderr)
                            # Click refresh button
                            refresh_btn = driver.find_element(By.ID, 'lnkupCaptcha')
                            refresh_btn.click()
                            time.sleep(1)
                            
                except Exception as e:
                    print(f"CAPTCHA attempt {attempt + 1} failed: {e}", file=sys.stderr)
                    if attempt < max_retries - 1:
                        time.sleep(1)
            
            if not captcha_solved:
                print("Failed to solve CAPTCHA after multiple attempts", file=sys.stderr)
                return None
            
            # Step 5: Enter password and submit
            print("Entering password...", file=sys.stderr)
            password_input.clear()
            password_input.send_keys(password)
            
            login_button = driver.find_element(By.ID, 'btnLogin')
            login_button.click()
            
            # Step 6: Wait for successful login
            print("Waiting for login to complete...", file=sys.stderr)
            time.sleep(5)
            
            # Check if login was successful by looking for student home page elements
            current_url = driver.current_url
            
            if 'StudentHome' in current_url or 'Dashboard' in current_url:
                print("✅ Login successful!", file=sys.stderr)
                
                # Extract all cookies
                cookies = driver.get_cookies()
                cookie_dict = {cookie['name']: cookie['value'] for cookie in cookies}
                
                print(f"Extracted {len(cookie_dict)} cookies", file=sys.stderr)
                return cookie_dict
            else:
                print(f"❌ Login failed. Current URL: {current_url}", file=sys.stderr)
                
                # Check for error messages
                try:
                    error_msg = driver.find_element(By.CLASS_NAME, 'error')
                    print(f"Error message: {error_msg.text}", file=sys.stderr)
                except:
                    pass
                
                return None
                
        except Exception as e:
            print(f"Login error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return None
            
        finally:
            if driver:
                print("Closing browser...", file=sys.stderr)
                driver.quit()
    
    def test_session(self, cookies: Dict) -> bool:
        """Test if the session cookies are valid"""
        driver = None
        try:
            driver = self.setup_driver(headless=True)
            
            # Add cookies
            driver.get('https://student.culko.in')
            for name, value in cookies.items():
                driver.add_cookie({'name': name, 'value': value})
            
            # Try to access protected page
            driver.get('https://student.culko.in/StudentHome.aspx')
            time.sleep(2)
            
            # Check if we're still on login page
            if 'Login' in driver.current_url:
                return False
            
            return True
            
        except Exception as e:
            print(f"Session test failed: {e}")
            return False
            
        finally:
            if driver:
                driver.quit()


def main():
    """Test the automated login or run as API service"""
    import argparse
    
    parser = argparse.ArgumentParser(description='CULKO Automated Login')
    parser.add_argument('--uid', type=str, help='Student UID')
    parser.add_argument('--password', type=str, help='Student password')
    parser.add_argument('--json-output', action='store_true', help='Output result as JSON')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode', default=True)
    parser.add_argument('--interactive-api', action='store_true', help='Run in interactive Web API mode (wait for files)')
    parser.add_argument('--session-id', type=str, help='Session ID for interactive Web API mode')
    
    args = parser.parse_args()
    
    solver = CULKOCaptchaSolver()
    
    # If UID and password provided via command line
    if args.uid and args.password:
        print("Starting automated login...", file=sys.stderr)
        
        # Check if Tesseract is available
        tesseract_available = False
        try:
            import subprocess
            result = subprocess.run(['tesseract', '--version'], 
                                  capture_output=True, 
                                  timeout=3)
            tesseract_available = (result.returncode == 0)
        except:
            pass
        
        # Use manual CAPTCHA mode if Tesseract not available and not in interactive mode
        use_manual_captcha = not tesseract_available and not args.interactive_api
        if use_manual_captcha:
            print("\n⚠️  Tesseract OCR not found - using manual CAPTCHA mode", file=sys.stderr)
            print("A browser will open. Please enter the CAPTCHA when prompted.\n", file=sys.stderr)
        
        cookies = solver.login_with_credentials(
            args.uid, 
            args.password, 
            headless=(args.headless and not use_manual_captcha),  # Don't use headless if manual CAPTCHA
            manual_captcha=use_manual_captcha,
            interactive_api=args.interactive_api,
            session_id=args.session_id
        )
        
        if args.interactive_api and args.session_id:
            result_path = f".sessions/{args.session_id}_result.json"
            if cookies:
                result = { 'success': True, 'cookies': cookies }
            else:
                result = { 'success': False, 'error': 'Login failed. Please check credentials or CAPTCHA.' }
                
            os.makedirs('.sessions', exist_ok=True)
            with open(result_path, "w") as f:
                json.dump(result, f)
            print(f"Interactive API login complete. Result written to {result_path}", file=sys.stderr)
            return

        elif args.json_output:
            # Output JSON for API consumption
            if cookies:
                result = {
                    'success': True,
                    'cookies': cookies
                }
            else:
                result = {
                    'success': False,
                    'error': 'Login failed. Please check credentials.'
                }
            # IMPORTANT: Only JSON to stdout, everything else to stderr
            print(json.dumps(result), flush=True)
        else:
            # Interactive mode
            if cookies:
                print("\n✅ Login successful!")
                print(f"Cookies saved: {list(cookies.keys())}")
                
                # Save cookies to file
                with open('culko_cookies_auto.json', 'w') as f:
                    json.dump(cookies, f, indent=2)
                
                print("Cookies saved to culko_cookies_auto.json")
                
                # Test the session
                print("\nTesting session validity...")
                if solver.test_session(cookies):
                    print("✅ Session is valid!")
                else:
                    print("❌ Session is invalid")
            else:
                print("\n❌ Login failed")
    else:
        # Interactive mode - get credentials from user
        uid = input("Enter your UID: ").strip()
        password = input("Enter your password: ").strip()
        
        print("\nStarting automated login...")
        cookies = solver.login_with_credentials(uid, password, headless=False)
        
        if cookies:
            print("\n✅ Login successful!")
            print(f"Cookies saved: {list(cookies.keys())}")
            
            # Save cookies to file
            with open('culko_cookies_auto.json', 'w') as f:
                json.dump(cookies, f, indent=2)
            
            print("Cookies saved to culko_cookies_auto.json")
            
            # Test the session
            print("\nTesting session validity...")
            if solver.test_session(cookies):
                print("✅ Session is valid!")
            else:
                print("❌ Session is invalid")
        else:
            print("\n❌ Login failed")


if __name__ == "__main__":
    main()
