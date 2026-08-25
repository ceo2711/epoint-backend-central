from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.source import Source

DEFAULT_SOURCES: tuple[tuple[str, str, str | None, int], ...] = (
    ("WEB_PAGE", "Página web", "Origen desde el sitio web", 10),
    ("WHATSAPP", "WhatsApp", None, 20),
    ("FACEBOOK", "Facebook", None, 30),
    ("INSTAGRAM", "Instagram", None, 40),
    ("REFERRAL", "Referido", None, 50),
    ("PHONE_CALL", "Llamada telefónica", None, 60),
    ("INFLUENCERS", "Influencers", "Referidos por influencers / creadores", 70),
    ("LANDING", "Landing EpointCredits", "Compra desde epointcredits.com", 15),
    ("OTHER", "Otro", None, 90),
)


def list_sources(db: Session, *, include_inactive: bool = False) -> list[Source]:
    query = select(Source).order_by(Source.sort_order, Source.name)
    if not include_inactive:
        query = query.where(Source.is_active.is_(True))
    return list(db.execute(query).scalars().all())


def get_source_by_code(db: Session, code: str) -> Source | None:
    clean = code.strip().upper()
    if not clean:
        return None
    return db.execute(select(Source).where(Source.code == clean)).scalar_one_or_none()


def require_active_source_code(
    db: Session,
    code: str | None,
    *,
    required: bool = False,
) -> str | None:
    if code is None or not str(code).strip():
        if required:
            raise ValueError("La fuente es obligatoria")
        return None

    source = get_source_by_code(db, str(code))
    if source is None or not source.is_active:
        raise ValueError("Fuente inválida o inactiva")
    return source.code


def ensure_default_sources(db: Session) -> None:
    # select(Source.code).scalars() ya devuelve str, no filas ORM.
    existing = set(db.execute(select(Source.code)).scalars().all())
    for code, name, description, sort_order in DEFAULT_SOURCES:
        if code in existing:
            continue
        db.add(
            Source(
                code=code,
                name=name,
                description=description,
                sort_order=sort_order,
                is_active=True,
            )
        )
