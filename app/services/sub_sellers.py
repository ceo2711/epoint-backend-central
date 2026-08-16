"""Sub-vendedores: elegibilidad por ventas y gestión bajo un SALES_REP.

Un vendedor titular es elegible si en al menos uno de los últimos 3 meses calendario
(mes actual + 2 anteriores) concretó 5 o más ventas (prospecto → cliente). Así, un mes
calificado renueva la ventana por 3 meses; se pierde solo tras 3 meses consecutivos
con menos de 5 ventas. Solo entonces puede dar de alta subvendedores (rol SUB_SELLER
con `parent_user_id`) y ver sus métricas. Un solo nivel de jerarquía.
"""

from __future__ import annotations

import logging
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
from app.services.role_access import (
    SUB_SELLER_ROLE,
    can_own_sub_sellers,
    can_supervise_sales_reps,
    is_sales_staff,
    is_sub_seller,
)
from app.services.sede_scope import effective_sede_id, sync_user_merchants_for_sede
from app.services.user_serialization import serialize_user

logger = logging.getLogger(__name__)

# Umbral de ventas concretadas en un mes calendario para calificar / renovar.
MIN_MONTHLY_SALES = 5
# Ventana: mes actual + (N-1) meses anteriores. Elegible si alguno ≥ umbral.
ELIGIBILITY_WINDOW_MONTHS = 3

# Alias retrocompatible.
MIN_PREVIOUS_MONTH_SALES = MIN_MONTHLY_SALES

SUB_SELLER_DEACTIVATED_LOGIN_DETAIL = (
    "Tu cuenta está desactivada. Comunicate con la administración de la empresa o con tu vendedor."
)


def calendar_month_bounds(
    year: int,
    month: int,
) -> tuple[datetime, datetime]:
    """Devuelve (inicio, fin_exclusivo) del mes calendario en UTC."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def shift_calendar_month(year: int, month: int, *, delta: int) -> tuple[int, int]:
    """Desplaza un mes calendario por ``delta`` (negativo = hacia atrás)."""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def previous_calendar_month_bounds(
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime, int, int]:
    """Devuelve (inicio, fin_exclusivo, año, mes) del mes calendario anterior en UTC."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    prev_year, prev_month = shift_calendar_month(ref.year, ref.month, delta=-1)
    start, end = calendar_month_bounds(prev_year, prev_month)
    return start, end, prev_year, prev_month


def eligibility_window_months(
    *,
    now: datetime | None = None,
    window: int = ELIGIBILITY_WINDOW_MONTHS,
) -> list[tuple[int, int, datetime, datetime]]:
    """Meses de la ventana (más reciente primero): (año, mes, inicio, fin_exclusivo)."""
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    months: list[tuple[int, int, datetime, datetime]] = []
    for offset in range(window):
        year, month = shift_calendar_month(ref.year, ref.month, delta=-offset)
        start, end = calendar_month_bounds(year, month)
        months.append((year, month, start, end))
    return months


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

    def eligibility(self, user: User, *, now: datetime | None = None) -> dict[str, Any]:
        """Elegible si algún mes de la ventana (3) tuvo ≥ ``MIN_MONTHLY_SALES`` ventas."""
        window = eligibility_window_months(now=now)
        month_rows: list[dict[str, Any]] = []
        for year, month, start, end in window:
            sales = self.count_concretized_sales(user.id, start=start, end_exclusive=end)
            month_rows.append(
                {
                    "year": year,
                    "month": month,
                    "sales": sales,
                    "qualified": sales >= MIN_MONTHLY_SALES,
                }
            )

        previous = month_rows[1] if len(month_rows) > 1 else month_rows[0]
        qualifying = [m for m in month_rows if m["qualified"]]
        is_sub = is_sub_seller(user)
        eligible = can_own_sub_sellers(user) and len(qualifying) > 0
        consecutive_below = 0
        for row in month_rows:
            if row["qualified"]:
                break
            consecutive_below += 1

        return {
            "eligible": eligible,
            "is_sub_seller": is_sub,
            # Compat: ventas del mes calendario anterior.
            "previous_month_sales": previous["sales"],
            "required_sales": MIN_MONTHLY_SALES,
            "threshold_exclusive": False,
            "previous_month": {"year": previous["year"], "month": previous["month"]},
            "window_months": ELIGIBILITY_WINDOW_MONTHS,
            "months": month_rows,
            "qualifying_months": len(qualifying),
            "consecutive_months_below_threshold": consecutive_below,
            "can_manage_sub_sellers": eligible,
        }

    def can_manage_sub_sellers(self, user: User) -> bool:
        if not can_own_sub_sellers(user):
            return False
        return bool(self.eligibility(user)["eligible"])

    def deactivate_active_sub_sellers(
        self,
        parent: User,
        *,
        commit: bool = True,
    ) -> int:
        """Desactiva subvendedores activos del padre y revoca sus sesiones."""
        if not can_own_sub_sellers(parent):
            return 0
        subs = list(
            self.db.execute(
                select(User).where(
                    User.parent_user_id == parent.id,
                    User.is_active.is_(True),
                )
            ).scalars().all()
        )
        if not subs:
            return 0

        from app.models.session import UserSession

        sub_ids = [sub.id for sub in subs]
        for sub in subs:
            sub.is_active = False
        sessions = self.db.execute(
            select(UserSession).where(
                UserSession.user_id.in_(sub_ids),
                UserSession.is_revoked.is_(False),
            )
        ).scalars().all()
        for session in sessions:
            session.is_revoked = True

        if commit:
            self.db.commit()
        else:
            self.db.flush()
        logger.info(
            "Desactivados %s subvendedores del vendedor #%s por pérdida de elegibilidad",
            len(subs),
            parent.id,
        )
        return len(subs)

    def enforce_parent_eligibility(
        self,
        parent: User,
        *,
        now: datetime | None = None,
        commit: bool = True,
    ) -> int:
        """Si el titular ya no es elegible, desactiva su equipo. Devuelve cuántos desactivó."""
        if not can_own_sub_sellers(parent):
            return 0
        if self.eligibility(parent, now=now)["eligible"]:
            return 0
        return self.deactivate_active_sub_sellers(parent, commit=commit)

    def enforce_all_ineligible_parents(self, *, now: datetime | None = None) -> dict[str, int]:
        """Barrido: desactiva equipos de titulares que perdieron la ventana de 3 meses."""
        parents = list(
            self.db.execute(
                select(User)
                .options(joinedload(User.role))
                .where(
                    User.parent_user_id.is_(None),
                    User.id.in_(select(User.parent_user_id).where(User.parent_user_id.is_not(None))),
                )
            )
            .unique()
            .scalars()
            .all()
        )
        parents_affected = 0
        deactivated = 0
        for parent in parents:
            if not can_own_sub_sellers(parent):
                continue
            n = self.enforce_parent_eligibility(parent, now=now, commit=False)
            if n:
                parents_affected += 1
                deactivated += n
        if deactivated:
            self.db.commit()
        return {
            "parents_checked": len(parents),
            "parents_affected": parents_affected,
            "sub_sellers_deactivated": deactivated,
        }

    def assert_sub_seller_may_login(self, user: User) -> None:
        """Bloquea login de subvendedores si el padre perdió elegibilidad (y desactiva el equipo)."""
        if not is_sub_seller(user):
            return
        # Fast-path: cuenta ya inactiva → mensaje sin recalcular elegibilidad.
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=SUB_SELLER_DEACTIVATED_LOGIN_DETAIL,
            )
        parent_id = user.parent_user_id
        if parent_id is None:
            return
        parent = (
            self.db.execute(
                select(User).options(joinedload(User.role)).where(User.id == parent_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        parent_eligible = parent is not None and self.can_manage_sub_sellers(parent)
        if not parent_eligible:
            if parent is not None:
                self.deactivate_active_sub_sellers(parent, commit=True)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=SUB_SELLER_DEACTIVATED_LOGIN_DETAIL,
            )

    def list_team_user_ids(self, user: User, *, include_self: bool = True) -> list[int]:
        """IDs del vendedor + sus subvendedores (para scopes de métricas de equipo)."""
        ids: list[int] = [user.id] if include_self else []
        if not can_own_sub_sellers(user):
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
                .options(
                    joinedload(User.role),
                    joinedload(User.area),
                    joinedload(User.sede),
                    joinedload(User.parent),
                )
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
                    "Para registrar subvendedores necesitás al menos "
                    f"{MIN_MONTHLY_SALES} ventas concretadas en alguno de los últimos "
                    f"{ELIGIBILITY_WINDOW_MONTHS} meses."
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

        sub_role = self.db.execute(select(Role).where(Role.code == SUB_SELLER_ROLE)).scalar_one_or_none()
        if sub_role is None:
            raise HTTPException(status_code=500, detail="Rol SUB_SELLER no configurado")

        ventas_area = self.db.execute(select(Area).where(Area.code == "VENTAS")).scalar_one_or_none()
        area_id = parent.area_id or (ventas_area.id if ventas_area else None)

        user = User(
            email=email_norm,
            password_hash=hash_password(password),
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=phone,
            role_id=sub_role.id,
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

    def set_sub_seller_active(self, actor: User, sub_seller_id: int, *, is_active: bool) -> User:
        """Activa/desactiva un subvendedor (titular de equipo o supervisor de sede)."""
        if can_supervise_sales_reps(actor):
            return self._set_sub_seller_active_as_supervisor(
                actor, sub_seller_id, is_active=is_active
            )

        self._require_parent_or_eligible(actor, require_eligible=False)
        if is_active and not self.can_manage_sub_sellers(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "No podés reactivar subvendedores sin elegibilidad. "
                    f"Necesitás al menos {MIN_MONTHLY_SALES} ventas en alguno de los últimos "
                    f"{ELIGIBILITY_WINDOW_MONTHS} meses."
                ),
            )
        sub = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
                .where(User.id == sub_seller_id, User.parent_user_id == actor.id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if sub is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subvendedor no encontrado")
        return self._apply_sub_seller_active(sub, is_active=is_active)

    def _set_sub_seller_active_as_supervisor(
        self, actor: User, sub_seller_id: int, *, is_active: bool
    ) -> User:
        sub = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
                .where(User.id == sub_seller_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if sub is None or not is_sub_seller(sub):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subvendedor no encontrado")
        actor_sede = effective_sede_id(actor)
        if actor_sede is not None and sub.sede_id != actor_sede:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subvendedor no encontrado")
        return self._apply_sub_seller_active(sub, is_active=is_active)

    def set_sales_staff_active(self, actor: User, user_id: int, *, is_active: bool) -> User:
        """Activa/desactiva un vendedor o subvendedor de la sede del supervisor."""
        if not can_supervise_sales_reps(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tenés permiso para activar o desactivar vendedores",
            )
        if user_id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No podés desactivar tu propia cuenta",
            )
        target = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
                .where(User.id == user_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if target is None or not (is_sales_staff(target) or is_sub_seller(target)):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendedor no encontrado")
        actor_sede = effective_sede_id(actor)
        if actor_sede is not None and target.sede_id != actor_sede:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendedor no encontrado")
        return self._apply_sub_seller_active(target, is_active=is_active)

    def _apply_sub_seller_active(self, sub: User, *, is_active: bool) -> User:
        sub.is_active = is_active
        if not is_active:
            from app.models.session import UserSession

            sessions = self.db.execute(
                select(UserSession).where(
                    UserSession.user_id == sub.id,
                    UserSession.is_revoked.is_(False),
                )
            ).scalars().all()
            for session in sessions:
                session.is_revoked = True
        self.db.commit()
        self.db.refresh(sub, attribute_names=["role", "area", "sede"])
        return sub

    def list_reassign_parents(self, actor: User) -> list[User]:
        """Vendedores titulares activos a los que se puede reasignar un subvendedor."""
        if not can_supervise_sales_reps(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tenés permiso para reasignar subvendedores",
            )
        query = (
            select(User)
            .options(
                joinedload(User.role),
                joinedload(User.area),
                joinedload(User.sede),
            )
            .join(Role)
            .where(
                Role.code.in_(("SALES_REP", "AREA_LEADER")),
                User.parent_user_id.is_(None),
                User.is_active.is_(True),
            )
            .order_by(User.first_name, User.last_name)
        )
        sede_id = effective_sede_id(actor)
        if sede_id is not None:
            query = query.where(User.sede_id == sede_id)
        rows = list(self.db.execute(query).unique().scalars().all())
        return [u for u in rows if can_own_sub_sellers(u)]

    def reassign_sub_seller(
        self,
        actor: User,
        sub_seller_id: int,
        *,
        new_parent_user_id: int,
    ) -> User:
        """Reasigna un subvendedor a otro vendedor titular (admin / gerente / líder ventas)."""
        if not can_supervise_sales_reps(actor):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tenés permiso para reasignar subvendedores",
            )

        sub = (
            self.db.execute(
                select(User)
                .options(
                    joinedload(User.role),
                    joinedload(User.area),
                    joinedload(User.sede),
                    joinedload(User.parent),
                )
                .where(User.id == sub_seller_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if sub is None or not is_sub_seller(sub):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subvendedor no encontrado")

        actor_sede = effective_sede_id(actor)
        if actor_sede is not None and sub.sede_id != actor_sede:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subvendedor no encontrado")

        new_parent = (
            self.db.execute(
                select(User)
                .options(joinedload(User.role), joinedload(User.area), joinedload(User.sede))
                .where(User.id == new_parent_user_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if new_parent is None or not can_own_sub_sellers(new_parent) or not new_parent.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El nuevo titular debe ser un vendedor activo sin padre",
            )
        if actor_sede is not None and new_parent.sede_id != actor_sede:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El nuevo titular debe pertenecer a tu sucursal",
            )
        if new_parent.id == sub.parent_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El subvendedor ya pertenece a ese vendedor",
            )

        sub.parent_user_id = new_parent.id
        if new_parent.sede_id is not None:
            sub.sede_id = new_parent.sede_id
            sync_user_merchants_for_sede(self.db, sub, new_parent.sede_id)

        # Si el nuevo titular no es elegible, el subvendedor queda inactivo hasta que
        # recupere elegibilidad y lo reactive. Si es elegible, reactivamos la cuenta.
        if not self.can_manage_sub_sellers(new_parent):
            if sub.is_active:
                from app.models.session import UserSession

                sub.is_active = False
                sessions = self.db.execute(
                    select(UserSession).where(
                        UserSession.user_id == sub.id,
                        UserSession.is_revoked.is_(False),
                    )
                ).scalars().all()
                for session in sessions:
                    session.is_revoked = True
        else:
            sub.is_active = True

        self.db.commit()
        refreshed = (
            self.db.execute(
                select(User)
                .options(
                    joinedload(User.role),
                    joinedload(User.area),
                    joinedload(User.sede),
                    joinedload(User.parent),
                )
                .where(User.id == sub.id)
            )
            .unique()
            .scalar_one()
        )
        logger.info(
            "Subvendedor #%s reasignado a vendedor #%s por actor #%s",
            sub_seller_id,
            new_parent_user_id,
            actor.id,
        )
        return refreshed

    def team_metrics(self, parent: User) -> dict[str, Any]:
        """Métricas del padre + cada subvendedor (mes actual y mes anterior)."""
        if not can_own_sub_sellers(parent):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo para vendedores titulares",
            )

        self.enforce_parent_eligibility(parent, commit=True)

        prev_start, prev_end, prev_year, prev_month = previous_calendar_month_bounds()
        now = datetime.now(timezone.utc)
        curr_start, curr_end = calendar_month_bounds(now.year, now.month)

        subs = self.list_sub_sellers(parent)
        members = [parent, *subs]

        def row_for(member: User) -> dict[str, Any]:
            return {
                "user": serialize_user(member).model_dump(),
                "is_self": member.id == parent.id,
                "is_sub_seller": is_sub_seller(member),
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
        if not can_own_sub_sellers(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo para vendedores titulares",
            )
        if require_eligible and not self.can_manage_sub_sellers(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Para registrar subvendedores necesitás al menos "
                    f"{MIN_MONTHLY_SALES} ventas concretadas en alguno de los últimos "
                    f"{ELIGIBILITY_WINDOW_MONTHS} meses."
                ),
            )
