"""Admin Console HIPAA Compliance Report (V1): persistent history of
HIPAA-relevant engineering changes/releases and their verification
evidence, plus the controls/evidence/status views built on top of it.

See db.py's own module docstring for why this package owns a real
SQLite-backed store rather than proxying to another service's database
(control-center has none of its own anywhere else in this repo today).
"""
