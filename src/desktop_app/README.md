# Desktop app + data pipeline

The PyQt6 desktop version of PS Finder, plus the scripts that build the
Supabase dataset. The live web/iOS app is in [`../docs/`](../docs/).

| File | Purpose |
|---|---|
| `app.py` | PyQt6 desktop app - Home / Detail / Recommendations |
| `collect_igdb.py` | Pulls PlayStation metadata from IGDB into `games.parquet` |
| `load_to_supabase.py` | Idempotent upsert of `games.parquet` into `public.games` |
| `igdb_data_collection.ipynb` | Original notebook (also downloads cover/screenshot images) |
| `Launch Recommender.bat` | Double-click launcher on Windows |
| `BUILD_EXE.md` | PyInstaller recipe for a standalone `.exe` |

See the top-level [`README.md`](../README.md) for setup and environment
variables.

## Run

```bash
python src/desktop_app/app.py
```

## Refresh the dataset (one time, or whenever IGDB changes)

```bash
python src/desktop_app/collect_igdb.py        # writes igdb_dataset/data/games.parquet
python src/desktop_app/load_to_supabase.py    # upserts into Supabase
```
