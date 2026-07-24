from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.influencer import Influencer
from app.models.sede import Sede
from app.services.influencers import INFLUENCERS_SOURCE_CODE, resolve_prospect_influencer_id


def test_resolve_prospect_influencer_requires_selection():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Sede.__table__, Influencer.__table__])
    session = sessionmaker(bind=engine)()
    sede = Sede(code="sede-1", name="Sede 1")
    session.add(sede)
    session.flush()

    try:
        resolve_prospect_influencer_id(
            session,
            source=INFLUENCERS_SOURCE_CODE,
            influencer_id=None,
            sede_id=sede.id,
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "influencer" in str(exc).lower()

    assert (
        resolve_prospect_influencer_id(
            session,
            source="OTHER",
            influencer_id=None,
            sede_id=sede.id,
        )
        is None
    )
