"""Cards por defecto al crear un tablero de cliente desde el template."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DefaultBoardCardComment:
    body: str


@dataclass(frozen=True)
class DefaultBoardCard:
    title: str
    description_md: str
    position: int
    requires_credentials: bool = False
    requires_file_upload: bool = False
    use_client_personal_data: bool = False
    comments: tuple[DefaultBoardCardComment, ...] = ()


EPOINT_SYSTEM_COMMENT_AUTHOR_EMAIL = "system@epoint.com"

_CLIENT_TODO_REPORTS_DESCRIPTION = """**Descripción**

Enviar el reporte descargado en PDF de [Experian](https://www.experian.com/) (Experian: Credit Report, FICO® Score & Financial Tools), generar los 3 reportes (Experian, Equifax y TransUnion). VER TUTORIAL ADJUNTADO DE COMO DESCARGAR LOS REPORTES.

**Importante:** los reportes deben estar recién generados (máximo 15 días de antigüedad). Si el reporte es más antiguo, será rechazado y deberás descargar uno nuevo.

Registrarse en [Equifax](https://www.equifax.com/) y [TransUnion](https://www.transunion.com/) (dejar usuario y clave de ambas en los comentarios)."""

_CLIENT_TODO_ACCOUNTS_DESCRIPTION = """**Descripción**

**1️⃣ Apertura de cuentas**

Por favor abrir las siguientes cuentas y enviarnos las credenciales una vez creadas:

- [ChexSystems](https://www.chexsystems.com)
- [Innovis Credit Report](https://www.innovis.com)
- [Experian Clarity Services](https://www.clarityservices.com)

**2️⃣ Congelar LexisNexis (obligatorio – debe hacerse vía llamada)**

Por favor congelar su reporte directamente con LexisNexis.

**Instrucciones:**

1. Ingrese a la página de LexisNexis: [Security Freeze - LexisNexis Risk Solutions Consumer Disclosure](https://consumer.risk.lexisnexis.com/freeze)
2. Baje hasta el final de la página donde aparecen las opciones para congelar.
3. Llame al número indicado para solicitar el Security Freeze: 📞 **1-800-456-1244**
4. Complete el proceso por teléfono.

**Credenciales de esta tarjeta**

Usa el formulario cifrado de abajo para **ChexSystems, Innovis y Clarity Services**.

Las claves de Experian, Equifax y TransUnion van en las tarjetas de la columna **Credenciales**."""

_CHEXSYSTEMS_COMMENT = """Paso a paso para registrarse en el portal de ChexSystems:

Ve al sitio oficial de [ChexSystems](https://www.chexsystems.com).

Haz clic en "Register" / "Registrarse" — para crear una cuenta como consumidor.

Completa el formulario con tus datos personales: nombre completo, dirección, fecha de nacimiento, número de Seguro Social (SSN) u otro identificador. Esto permite verificar identidad.

Contesta las preguntas de seguridad / verificación de identidad que te presenten (algunas agencias de verificación lo hacen como parte del registro).

Elige un nombre de usuario y una contraseña, acepta los términos del servicio y completa el registro."""

_INNOVIS_COMMENT = """Paso a paso para aperturar cuenta en Innovis:

1. Ingresa a [Sign In](https://www.innovis.com)
2. Allí selecciona la opción para pedir tu "Innovis Credit Report". Esa solicitud de informe es también el primer paso para generar lo que llaman tu [Innovis.com Account](https://www.innovis.com) (cuenta personal).
3. Completa el formulario con tus datos personales: nombre, fecha de nacimiento, Social Security Number (SSN), número de teléfono, dirección, etc.
4. Verifica tu identidad. Innovis puede usar la información que diste para chequear tu identidad, incluso a través de tu operador móvil.
5. Si todo está correcto, te crearán la cuenta para que puedas ver tu reporte en línea, y desde ahí también podrás hacer otros trámites (bloqueos, alertas de fraude, disputas, etc.)."""

_CLARITY_COMMENT = """En el caso de Experian Clarity Services no creas un usuario y clave como tal, así que te indico los pasos para este caso:

Entra al portal oficial: [Experian's Clarity Services | Clarity Services, Inc.](https://www.clarityservices.com)

Haz clic en: ➡️ **ACCESS YOUR CLARITY CREDIT REPORT**

Completa tu información personal y responde las preguntas de seguridad.

Si el sistema no puede verificarte automáticamente, te pedirá subir documentos (foto de tu ID + factura o estado de cuenta con tu dirección).

Una vez verificado, podrás ver tu reporte completo y enviárnoslo."""

_CLIENT_TODO_BANKS_DESCRIPTION = """**Descripción**

Colocar una lista de los bancos con los que tiene alguna relación, bien sea tarjeta de débito/crédito. Esto incluye:

- Personal
- Del negocio/negocios
- Tarjetas de crédito
- Incluso cuentas o bancos cerrados"""

TAXES_CARD_TITLE = "Informe de Taxes"
TAXES_CARD_COLUMN = "Ideas a realizar"

_CLIENT_TODO_TAXES_DESCRIPTION = """**Descripción**

Esta tarjeta **no es obligatoria para completar el onboarding**.

El informe de taxes (Tax Return / declaración de impuestos o Tax Transcript del IRS de los últimos 2 años fiscales) se pide **solo cuando una entidad financiera lo requiera** más adelante.

Cuando te lo soliciten:
- Subí un documento fiscal legible (Form 1040, Tax Return, IRS Transcript u otro informe oficial)
- Debe verse el nombre del contribuyente
- Cubre los últimos 2 años fiscales

Si el archivo no es un informe de taxes válido, será rechazado y deberás volver a subirlo."""

_PERSONAL_DATA_PLACEHOLDER = """**Descripción**

Nombre:

Email:

Phone:

Address:

SSN:

Fecha Nacimiento:"""

_CREDENTIALS_EXPERIAN_DESCRIPTION = """**Descripción**

Carga aquí el usuario y la contraseña de **Experian** con el formulario cifrado de esta tarjeta (no los escribas en comentarios)."""

_CREDENTIALS_EQUIFAX_DESCRIPTION = """**Descripción**

Carga aquí el usuario y la contraseña de **Equifax** con el formulario cifrado de esta tarjeta (no los escribas en comentarios)."""

_CREDENTIALS_TRANSUNION_DESCRIPTION = """**Descripción**

Carga aquí el usuario y la contraseña de **TransUnion** con el formulario cifrado de esta tarjeta (no los escribas en comentarios)."""

_CREDENTIALS_CHEXSYSTEMS_DESCRIPTION = """**Descripción**

Carga aquí el usuario y la contraseña de **ChexSystems** con el formulario cifrado de esta tarjeta."""

_CREDENTIALS_INNOVIS_DESCRIPTION = """**Descripción**

Carga aquí el usuario y la contraseña de **Innovis** con el formulario cifrado de esta tarjeta."""

_INQUIRIES_DESCRIPTION = """**Descripción**

Lista las inquiries (consultas de crédito) de este buró: acreedor, fecha y tipo (hard/soft)."""

_ACCOUNTS_TEMPLATE_DESCRIPTION = """**Descripción**

**Nombre de la cuenta**

Balance:

Account number:

Fecha abierta:

Estado:

---

**Nombre de la cuenta**

Balance:

Límite:

Uso:

Notas:"""

# Secuencia de referencia para el Funder (ya no se siembra en tableros nuevos).
FUNDER_PERSONAL_SEQUENCE_TITLES: tuple[str, ...] = (
    "JP Morgan Chase",
    "Sofi Bank",
    "Navy Federal Credit Union",
    "Lightstream By Truist",
    "CAPITAL ONE",
    "DISCOVER CARD",
    "Citi Bank",
    "Upgrade",
    "Citizens Bank",
    "Truist Bank",
    "Navy Federal Credit Union",
    "Upstart",
    "One Key",
)

FUNDER_BUSINESS_SEQUENCE_TITLES: tuple[str, ...] = (
    "JP Morgan Chase",
    "Truist Bank",
    "FNBO - OZK",
    "Citizens Bank",
    "Bank OZK",
    "AOF",
    "Bluevine",
    "First Horizon",
    "PNC Bank",
    "Wells Fargo",
    "American Express",
    "US Bank",
    "Citi Bank Business",
    "Paypal Business Loan",
)

_COMPLETED_INQUIRIES_1_DESCRIPTION = """**Descripción**

ALLY FINANCIAL — Jul 11, 2025

ALLY FINANCIAL — Jul 11, 2025

GLOBAL LENDING SERVICE — Jul 11, 2025

CREDIT ONE BANK NA — Apr 28, 2025

CITIBANK NA / BEST BUY — Apr 26, 2025

THD/CBNA — Apr 8, 2024"""

_COMPLETED_INQUIRIES_2_DESCRIPTION = """**Descripción**

ALLY FINANCIAL — Jul 11, 2025 (Auto Financing)

AMERICAN CREDIT ACCE — Jul 11, 2025 (Auto Financing)

AN TOY SCION WINTER — Jul 11, 2025 (Auto Dealers)

AUTONATION FINANCE — Jul 11, 2025 (Personal Loans)

GLOBAL LENDING SERVI — Jul 11, 2025 (Auto Financing)

SOUTHEAST TOYOTA FIN — Jul 11, 2025 (Auto Financing)"""

_COMPLETED_INQUIRIES_3_DESCRIPTION = """**Descripción**

ALLY FINANCIAL — Jul 11, 2025"""


DEFAULT_BOARD_CARDS_BY_COLUMN: dict[str, tuple[DefaultBoardCard, ...]] = {
    "Client TO DO": (
        DefaultBoardCard(
            title="Reportes: Experian, Equifax y TransUnion",
            description_md=_CLIENT_TODO_REPORTS_DESCRIPTION,
            position=0,
            requires_file_upload=True,
        ),
        DefaultBoardCard(
            title="Apertura de Cuentas & Freeze",
            description_md=_CLIENT_TODO_ACCOUNTS_DESCRIPTION,
            position=1,
            requires_credentials=True,
            comments=(
                DefaultBoardCardComment(body=_CHEXSYSTEMS_COMMENT),
                DefaultBoardCardComment(body=_INNOVIS_COMMENT),
                DefaultBoardCardComment(body=_CLARITY_COMMENT),
            ),
        ),
        DefaultBoardCard(
            title="Lista de bancos con relacion",
            description_md=_CLIENT_TODO_BANKS_DESCRIPTION,
            position=2,
        ),
    ),
    TAXES_CARD_COLUMN: (
        DefaultBoardCard(
            title=TAXES_CARD_TITLE,
            description_md=_CLIENT_TODO_TAXES_DESCRIPTION,
            position=0,
            requires_file_upload=True,
        ),
    ),
    "Credenciales": (
        DefaultBoardCard(
            title="Datos personales",
            description_md=_PERSONAL_DATA_PLACEHOLDER,
            position=0,
            use_client_personal_data=True,
        ),
        DefaultBoardCard(
            title="Experian",
            description_md=_CREDENTIALS_EXPERIAN_DESCRIPTION,
            position=1,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title="Equifax",
            description_md=_CREDENTIALS_EQUIFAX_DESCRIPTION,
            position=2,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title="TransUnion",
            description_md=_CREDENTIALS_TRANSUNION_DESCRIPTION,
            position=3,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title="ChexSystems",
            description_md=_CREDENTIALS_CHEXSYSTEMS_DESCRIPTION,
            position=4,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title="Innovis",
            description_md=_CREDENTIALS_INNOVIS_DESCRIPTION,
            position=5,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title="Clarity Services",
            description_md="",
            position=6,
            requires_file_upload=True,
        ),
    ),
    "Experian": (
        DefaultBoardCard(
            title="Accounts",
            description_md=_ACCOUNTS_TEMPLATE_DESCRIPTION,
            position=0,
        ),
        DefaultBoardCard(
            title="Inquiries",
            description_md=_INQUIRIES_DESCRIPTION,
            position=1,
        ),
    ),
    "Transunion": (
        DefaultBoardCard(
            title="Accounts",
            description_md=_ACCOUNTS_TEMPLATE_DESCRIPTION,
            position=0,
        ),
        DefaultBoardCard(
            title="Inquiries",
            description_md=_INQUIRIES_DESCRIPTION,
            position=1,
        ),
    ),
    "Equifax": (
        DefaultBoardCard(
            title="Accounts",
            description_md=_ACCOUNTS_TEMPLATE_DESCRIPTION,
            position=0,
        ),
        DefaultBoardCard(
            title="Inquiries",
            description_md=_INQUIRIES_DESCRIPTION,
            position=1,
        ),
    ),
    "Completed": (
        DefaultBoardCard(
            title="Inquiries",
            description_md=_COMPLETED_INQUIRIES_1_DESCRIPTION,
            position=0,
        ),
        DefaultBoardCard(
            title="Inquiries",
            description_md=_COMPLETED_INQUIRIES_2_DESCRIPTION,
            position=1,
        ),
        DefaultBoardCard(
            title="Inquiries",
            description_md=_COMPLETED_INQUIRIES_3_DESCRIPTION,
            position=2,
        ),
    ),
}


def default_cards_for_column(column_title: str) -> tuple[DefaultBoardCard, ...]:
    return DEFAULT_BOARD_CARDS_BY_COLUMN.get(column_title, ())


def is_taxes_card(title: str | None) -> bool:
    normalized = (title or "").strip().lower()
    return "tax" in normalized or "impuesto" in normalized


def is_optional_onboarding_card(title: str | None) -> bool:
    """Cards que no bloquean el cierre del onboarding (p. ej. taxes a pedido)."""
    return is_taxes_card(title)
