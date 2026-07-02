#!/usr/bin/env python3
"""Sincroniza contratos DocuSign, vincula clientes por email y archiva PDFs firmados."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal
from app.services.docusign.service import DocusignService


def main() -> None:
    db = SessionLocal()
    try:
        stats = DocusignService(db).sync_all_envelopes_from_docusign(notify=False)
        print("DocuSign sync completado:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
