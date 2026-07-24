from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.source import Source
from app.services.sources import ensure_default_sources, list_sources, require_active_source_code


def test_ensure_default_sources_includes_influencers():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Source.__table__])
    session = sessionmaker(bind=engine)()

    ensure_default_sources(session)
    session.commit()

    codes = [row.code for row in list_sources(session, include_inactive=True)]
    assert "INFLUENCERS" in codes
    assert "WEB_PAGE" in codes
    assert require_active_source_code(session, "influencers") == "INFLUENCERS"
