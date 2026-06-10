# Building a standalone .exe

The app runs with `python app.py` (or double-click `Launch Recommender.bat`).
For a distributable single .exe (no Python needed on the target machine):

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --name "PSGameRecommender" `
    --hidden-import=supabase --hidden-import=postgrest --hidden-import=gotrue `
    --hidden-import=storage3 --hidden-import=realtime --hidden-import=supafunc `
    app.py
```

Output: `dist/PSGameRecommender.exe` (~80–110 MB).

## Optional flags

- `--icon=app.ico` — bundle a custom icon
- `--noconfirm` — overwrite previous build without prompting
- `--add-data "README.md;."` — bundle extra files

## Common issues

- **Antivirus flags the exe**: PyInstaller bundles trip heuristic detection. Sign the binary or add an AV exclusion for personal use.
- **Missing supabase submodules at runtime**: add more `--hidden-import` flags for whichever the traceback names.
- **App opens then closes immediately**: rebuild without `--windowed` to see the console error.

## After rotation

If you rotate the Supabase publishable key, either:
- update the `SUPABASE_ANON_KEY` constant at the top of `app.py` and rebuild, or
- set the `SUPABASE_ANON_KEY` env var before launching (no rebuild needed).
