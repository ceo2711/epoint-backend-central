"""Sub-vendedores: elegibilidad por ventas del mes anterior y gestión bajo un SALES_REP.

Un vendedor es elegible si concretó más de 5 ventas (prospecto → cliente) en el
mes calendario anterior. Solo entonces puede dar de alta subvendedores (SALES_REP
con `parent_user_id`) y ver sus métricas. Un solo nivel de jerarquía.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.security import hash_password
from app.models.area import Area
from app.models.client import Client
from app.models.prospect import Prospect
from app.models.role import Role
from app.models.user import User
from app.services.sede_scope import sync_user_merchants_for_sede
from app.services.user_serialization import serialize_user

# "Más de 5" → se habilita con 6 o más conversiones en el mes anterior.
MIN_PREVIOUS_MONTH_SALES = 5


def previous_calendar_month_bounds(
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime, int, int]:
    """Devuelve (inicio, fin_exclusivo, año, mes) del mes calendario anterior en UTC."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    year = ref.year
    month = ref.month
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    start = datetime(prev_year, prev_month, 1, tzinfo=timezone.utc)
    last_day = monthrange(prev_year, prev_month)[1]
    end = datetime(prev_year, prev_month, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    # Usamos fin exclusivo = primer instante del mes actual.
    current_month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    return start, current_month_start, prev_year, prev_month


class SubSellerService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def count_concretized_sales(
        self,
        user_id: int,
        *,
        start: datetime,
        end_exclusive: datetime,
    ) -> int:
        """Ventas concretadas = prospectos del vendedor convertidos a cliente en el período.

        Se usa `Client.created_at` del cliente convertido (momento de la conversión).
        """
        count = self.db.execute(
            select(func.count())
            .select_from(Prospect)
            .join(Client, Client.id == Prospect.converted_client_id)
            .where(
                Prospect.assigned_to_user_id == user_id,
                Prospect.converted_client_id.is_not(None),
                Client.created_at >= start,
                Client.created_at < end_exclusive,
            )
        ).scalar()
        return int(count or 0)

    def eligibility(self, user: User) -> dict[str, Any]:
        start, end, year, month = previous_calendar_month_bounds()
        sales = self.count_concretized_sales(user.id, start=start, end_exclusive=end)
        is_sales = user.role.code == "SALES_REP"
        is_sub = user.parent_user_id is not None
        eligible = is_sales and not is_sub and sales > MIN_PREVIOUS_MONTH_SALES
        return {
            "eligible": eligible,
            "is_sub_seller": is_sub,
            "previous_month_sales": sales,
            "required_sales": MIN_PREVIOUS_MONTH_SALES,
            "threshold_exclusive": True,
            "previous_month": {"year": year, "month": month},
            "can_manage_sub_sellers": eligible,
        }

    def can_manage_sub_sellers(self, user: User) -> bool:
        if user.role.code != "SALES_REP" or user.parent_user_id is not None:
            return False
        return bool(self.eligibility(user)["eligible"])

    def list_team_user_ids(self, user: User, *, include_self: bool = True) -> list[int]:
        """IDs del vendedor + sus subvendedores (para scopes de datos/métricas)."""
        ids: list[int] = [user.id] if include_self else []
        if user.role.code != "SALES_REP":
            return ids
        children = self.db.execute(
            select(User.id).where(User.parent_user_id == user.id)
        ).scalars().all()
        ids.extend(int(child_id) for child_id in children)
        return ids

    def list_sub_sellers(self, parent: User) -> list[User]:
        self._require_parent_or_eligible(parent, require_eligible=False)
        return list(
            self.db.execute(
                select(User)
                .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
                .where(User.parent_user_id == parent.id)
                .order_by(User.created_at.desc())
            )
            .unique()
            .scalars()
            .all()
        )

    def create_sub_seller(
        self,
        parent: User,
        *,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        phone: str | None = None,
    ) -> User:
        if not self.can_manage_sub_sellers(parent):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Para registrar subvendedores necesitás más de "
                    f"{MIN_PREVIOUS_MONTH_SALES} ventas concretadas en el mes anterior."
                ),
            )
        if parent.sede_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tu usuario no tiene sede asignada",
            )

        email_norm = email.strip().lower()
        existing = self.db.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El email ya está registrado")

        sales_role = self.db.execute(select(Role).where(Role.code == "SALES_REP")).scalar_one_or_none()
        if sales_role is None:
            raise HTTPException(status_code=500, detail="Rol SALES_REP no configurado")

        ventas_area = self.db.execute(select(Area).where(Area.code == "VENTAS")).scalar_one_or_none()
        area_id = parent.area_id or (ventas_area.id if ventas_area else None)

        user = User(
            email=email_norm,
            password_hash=hash_password(password),
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=phone,
            role_id=sales_role.id,
            area_id=area_id,
            sede_id=parent.sede_id,
            parent_user_id=parent.id,
            must_change_password=True,
            is_active=True,
        )
        self.db.add(user)
        self.db.flush()
        sync_user_merchants_for_sede(self.db, user, parent.sede_id)
        self.db.commit()
        refreshed = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
                .where(User.id == user.id)
            )
            .unique()
            .scalar_one()
        )
        return refreshed

    def set_sub_seller_active(self, parent: User, sub_seller_id: int, *, is_active: bool) -> User:
        self._require_parent_or_eligible(parent, require_eligible=False)
        sub = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
                .where(User.id == sub_seller_id, User.parent_user_id == parent.id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if sub is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subvendedor no encontrado")
        sub.is_active = is_active
        self.db.commit()
        self.db.refresh(sub, attribute_names=["role", "area", "sede"])
        return sub

    def team_metrics(self, parent: User) -> dict[str, Any]:
        """Métricas del padre + cada subvendedor (mes actual y mes anterior)."""
        if parent.role.code != "SALES_REP":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo para vendedores")
        if parent.parent_user_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Los subvendedores no gestionan equipo",
            )

        prev_start, prev_end, prev_year, prev_month = previous_calendar_month_bounds()
        now = datetime.now(timezone.utc)
        curr_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        if now.month == 12:
            curr_end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            curr_end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)

        subs = self.list_sub_sellers(parent)
        members = [parent, *subs]

        def row_for(member: User) -> dict[str, Any]:
            return {
                "user": serialize_user(member).model_dump(),
                "is_self": member.id == parent.id,
                "is_sub_seller": member.parent_user_id is not None,
                "sales_previous_month": self.count_concretized_sales(
                    member.id, start=prev_start, end_exclusive=prev_end
                ),
                "sales_current_month": self.count_concretized_sales(
                    member.id, start=curr_start, end_exclusive=curr_end
                ),
                "prospects_open": self._count_open_prospects(member.id),
            }

        member_rows = [row_for(m) for m in members]
        return {
            "previous_month": {"year": prev_year, "month": prev_month},
            "current_month": {"year": now.year, "month": now.month},
            "eligibility": self.eligibility(parent),
            "members": member_rows,
            "totals": {
                "sales_previous_month": sum(r["sales_previous_month"] for r in member_rows),
                "sales_current_month": sum(r["sales_current_month"] for r in member_rows),
                "prospects_open": sum(r["prospects_open"] for r in member_rows),
                "sub_sellers": len(subs),
            },
        }

    def _count_open_prospects(self, user_id: int) -> int:
        from app.models.enums import ProspectStatus

        count = self.db.execute(
            select(func.count())
            .select_from(Prospect)
            .where(
                Prospect.assigned_to_user_id == user_id,
                Prospect.converted_client_id.is_(None),
                Prospect.status != ProspectStatus.LEAD_CERRADO.value,
            )
        ).scalar()
        return int(count or 0)

    def _require_parent_or_eligible(self, user: User, *, require_eligible: bool) -> None:
        if user.role.code != "SALES_REP":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo para vendedores")
        if user.parent_user_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Los subvendedores no pueden gestionar otros subvendedores",
            )
        if require_eligible and not self.can_manage_sub_sellers(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Para registrar subvendedores necesitás más de "
                    f"{MIN_PREVIOUS_MONTH_SALES} ventas concretadas en el mes anterior."
                ),
            )
