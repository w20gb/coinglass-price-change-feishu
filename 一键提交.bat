@echo off
title One-Click Git Push (v2.4 Auto-Pull)
color 0A

:: 1. Initialize Git
if not exist ".git" (
    echo [INFO] Initializing Git repository...
    git init
    git branch -M main
)

:: 2. Check Remote
git remote get-url origin >nul 2>&1
if %errorlevel% equ 0 goto commit_step

echo.
echo [WARN] No remote repository found!
echo [STEP] Please create a new repository on GitHub.
set /p "repo_url=[INPUT] Paste your GitHub Repository URL here: "

if "%repo_url%"=="" (
    color 0C
    echo [ERROR] URL cannot be empty.
    pause
    exit
)

git remote add origin %repo_url%
echo [INFO] Remote 'origin' added.

:commit_step
:: 3. Interactive Commit
echo.
set "msg="
set /p "msg=[INPUT] Enter commit message (Enter for 'Auto Update'): "
if "%msg%"=="" set "msg=Auto Update"

echo.
echo [INFO] Adding all files...
git add .

echo [INFO] Committing...
git commit -m "%msg%"

echo.
echo [INFO] Pulling latest changes from remote...
git pull --rebase origin main

echo.
echo [INFO] Pushing to remote...
git push origin main
if %errorlevel% equ 0 goto success

:: Fallback if rebase failed or other issues
echo [WARN] Standard push failed. Using force push (safe mode)...
:: 只在 rebase 失败但此时确实需要覆盖时使用，这里我们尽量保守，先再次提示
echo [ERROR] Push failed! You might need to manually run: git pull origin main
pause
exit

:success
echo.
echo [SUCCESS] Code deployed to GitHub!
echo [INFO] GitHub Actions should be triggering soon.
timeout /t 5
