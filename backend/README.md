# qa-platform backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

默认数据库为 `./qa-platform.db`，可通过 `DATABASE_URL` 覆盖。
