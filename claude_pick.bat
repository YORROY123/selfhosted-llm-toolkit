@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"

echo 啟動 llm 分流代理...
start "llm router" /min python claude_router.py

set TRIES=0
:wait
set /a TRIES+=1
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',8787);exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 goto ready
if %TRIES% GEQ 25 (
  echo.
  echo 代理起不來。在這個資料夾開終端機跑 python claude_router.py 看它印什麼錯誤。
  pause
  exit /b 1
)
goto wait

:ready
rem 刻意不設 ANTHROPIC_AUTH_TOKEN ——
rem 要讓 Claude Code 照常用你自己的 claude.ai 登入，代理只負責轉手。
set ANTHROPIC_BASE_URL=http://127.0.0.1:8787
set CLAUDE_CODE_MAX_CONTEXT_TOKENS=65536

echo.
echo ================================================
echo  進去之後打 /model 選要用誰的模型：
echo.
echo    Opus / Sonnet ...   真 Claude（你自己的登入）
echo    my-strong             自己機器上的 · 寫程式用
echo    my-fast           自己機器上的 · 快
echo ================================================
echo.

claude %*

echo.
echo 結束了。背景那個 "llm router" 視窗關掉就完全收工。
pause
