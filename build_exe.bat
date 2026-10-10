@echo off
REM Builds dist\WebsiteDetective\WebsiteDetective.exe  (run from the project folder)
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
pip install -r requirements.txt || goto :err
pyinstaller --noconfirm --clean --windowed --name WebsiteDetective ^
  --collect-submodules website_detective ^
  --hidden-import lxml.etree --hidden-import lxml._elementpath ^
  --exclude-module tkinter --exclude-module playwright ^
  main.py || goto :err
echo.
echo Built: dist\WebsiteDetective\WebsiteDetective.exe
echo Browser rendering is excluded from the EXE; see README for the optional Playwright variant.
exit /b 0
:err
echo Build failed.
exit /b 1
