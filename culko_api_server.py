"""
CULKO Automation API Server
FastAPI server that handles automated CULKO login with CAPTCHA solving
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from automated_culko_login import CULKOCaptchaSolver

app = FastAPI(title="CULKO Automation API")

class LoginRequest(BaseModel):
    uid: str
    password: str
    headless: bool = True

class LoginResponse(BaseModel):
    success: bool
    cookies: Optional[dict] = None
    error: Optional[str] = None

@app.post("/api/auto-login", response_model=LoginResponse)
async def auto_login(request: LoginRequest):
    """
    Automated login to CULKO portal with CAPTCHA solving
    
    Args:
        uid: Student UID
        password: Student password
        headless: Run browser in headless mode
        
    Returns:
        Session cookies if successful
    """
    try:
        solver = CULKOCaptchaSolver()
        cookies = solver.login_with_credentials(
            uid=request.uid,
            password=request.password,
            headless=request.headless
        )
        
        if cookies:
            return LoginResponse(
                success=True,
                cookies=cookies,
                error=None
            )
        else:
            return LoginResponse(
                success=False,
                cookies=None,
                error="Login failed. Please check your credentials and try again."
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
