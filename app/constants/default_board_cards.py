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

_CREDENTIALS_FORM_NOTE = (
    "Al finalizar, escribí el usuario y la contraseña en un **comentario** de esta tarjeta "
    "para que un asesor pueda tomarlos."
)

_CLIENT_TODO_REPORTS_DESCRIPTION = """Enviar el reporte descargado en PDF de Experian (Experian, Equifax y TransUnion).

1. Ingrese a [https://www.experian.com/](https://www.experian.com/) y seleccione Sign In.
2. Inicie sesión con el correo electrónico y la contraseña de su cuenta de Experian.
3. Dentro de su cuenta, diríjase a la sección de Credit Reports.
4. Seleccione la opción para consultar los reportes de los tres burós: Experian, Equifax y TransUnion.
5. Si su cuenta gratuita solo muestra el reporte de Experian, seleccione la opción para actualizar al plan de pago que incluya los tres reportes. Esta opción puede aparecer como Buy your report.
6. Una vez realizado el pago, abra por separado los reportes de:
    * Experian
    * Equifax
    * TransUnion
7. Descargue cada reporte completo en formato PDF. Si no aparece la opción de descarga, seleccione Imprimir y luego Guardar como PDF.
8. Guarde los archivos con los siguientes nombres:
    * Nombre y apellido – Experian
    * Nombre y apellido – Equifax
    * Nombre y apellido – TransUnion
9. Adjunte los tres archivos PDF en esta tarjeta.

**Importante**

* El cliente debe realizar el pago directamente desde su cuenta.
* Los tres reportes deben estar completos, actualizados y ser legibles.
* Los reportes deben estar recién generados (máximo 15 días de antigüedad). Si el reporte es más antiguo, será rechazado y deberás descargar uno nuevo."""

_CLIENT_TODO_ACCOUNTS_DESCRIPTION = """Apertura de cuentas: por favor abrir las siguientes cuentas de burós secundarios. **Nota:** En el caso de Experian Clarity Services no creas un usuario y clave, solamente generas un reporte de crédito que debes adjuntar en su tarjeta.

* [ChexSystems](https://www.chexsystems.com)
* [Innovis Credit Report](https://www.innovis.com/)
* [Experian Clarity Services](https://consumers.clarityservices.com/reports)

Las claves de ChexSystems e Innovis van en las tarjetas de la columna **Credenciales** (dejálas en un comentario). El reporte de Clarity se adjunta en la tarjeta **Experian Clarity Services**."""

_CLIENT_TODO_BANKS_DESCRIPTION = """Colocar en los comentarios una lista completa de todos los bancos con los que tiene o ha tenido alguna relación financiera. Incluya:

* Cuentas personales o de negocio
* Tarjetas de débito
* Tarjetas de crédito
* Cuentas bancarias cerradas

Utilice el siguiente formato:

**Bancos activos**
1. [Nombre del banco] ([tipo de cuenta o tarjeta])
2. [Nombre del banco] ([tipo de cuenta o tarjeta])

**Bancos con cuentas cerradas**
1. [Nombre del banco] ([tipo de cuenta o tarjeta])
2. [Nombre del banco] ([tipo de cuenta o tarjeta])

Importante: solo necesitamos el nombre del banco y el tipo de producto. No incluya números de cuenta, números de tarjeta, contraseñas ni ninguna otra información confidencial."""

TAXES_CARD_TITLE = "Informe de Taxes"
TAXES_CARD_COLUMN = "Client TO DO"
ACCOUNTS_CARD_TITLE = "Apertura de Cuentas (Buros Secundarios)"
BANKS_CARD_TITLE = "Lista de bancos con relación"
CLARITY_CARD_TITLE = "Experian Clarity Services"

CARD_TITLE_ALIASES = {
    "Apertura de Cuentas & Freeze": ACCOUNTS_CARD_TITLE,
    "Lista de bancos con relacion": BANKS_CARD_TITLE,
    "Clarity Services": CLARITY_CARD_TITLE,
}

_CLIENT_TODO_TAXES_DESCRIPTION = """Esta tarjeta **no es obligatoria para completar el onboarding**.

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

_CREDENTIALS_EXPERIAN_DESCRIPTION = f"""Crear cuenta en Experian

1. Ingrese al portal oficial de Experian: [https://www.experian.com/](https://www.experian.com/)
2. Cree una cuenta nueva siguiendo las instrucciones del portal.
3. {_CREDENTIALS_FORM_NOTE}"""

_CREDENTIALS_EQUIFAX_DESCRIPTION = f"""Crear cuenta en Equifax

1. Ingrese al portal oficial de myEquifax: [https://my.equifax.com/](https://my.equifax.com/)
2. Cree una cuenta nueva siguiendo las instrucciones del portal.
3. Si necesita adquirir una suscripción para acceder a la información requerida, puede realizar el pago y cancelarla después de completar el proceso para evitar futuros cargos mensuales.
4. {_CREDENTIALS_FORM_NOTE}"""

_CREDENTIALS_TRANSUNION_DESCRIPTION = f"""Crear cuenta en TransUnion

1. Ingrese al portal oficial de TransUnion: [https://www.transunion.com/free-credit-report](https://www.transunion.com/free-credit-report)
2. Cree una cuenta nueva siguiendo las instrucciones del portal.
3. {_CREDENTIALS_FORM_NOTE}"""

_CREDENTIALS_CHEXSYSTEMS_DESCRIPTION = f"""## Crear cuenta en ChexSystems

1. Ingrese al portal oficial de ChexSystems: [https://www.chexsystems.com/request-reports/consumer-disclosure](https://www.chexsystems.com/request-reports/consumer-disclosure)
2. Seleccione **Register** o **Start Registration**.
3. Complete el formulario con la información personal solicitada.
4. Cree el usuario y la contraseña para acceder al Consumer Portal.
5. Complete el proceso de verificación de identidad. Si anteriormente colocó una alerta o congelamiento de seguridad, el sistema podría solicitarle el PIN o la contraseña correspondiente.
6. Confirme su correo electrónico o el código de seguridad que reciba.
7. Inicie sesión para comprobar que puede acceder al Consumer Portal.
8. {_CREDENTIALS_FORM_NOTE}"""

_CREDENTIALS_INNOVIS_DESCRIPTION = f"""## Para abrir la cuenta en Innovis

1. Ingresa a [Sign In | Innovis](https://www.innovis.com/login/index).
2. Selecciona la opción para solicitar tu **Innovis Credit Report**. Esta solicitud también es el primer paso para crear lo que se conoce como tu **Innovis.com Account** o cuenta personal.
3. Completa el formulario con tus datos personales: nombre, fecha de nacimiento, Social Security Number (SSN), número de teléfono, dirección, entre otros.
4. Verifica tu identidad. Innovis puede utilizar la información proporcionada para confirmar tu identidad, incluso mediante tu operador de telefonía móvil.
5. Si toda la información es correcta, te permitirá crear tu cuenta con usuario y clave.
6. {_CREDENTIALS_FORM_NOTE}"""

_CREDENTIALS_CLARITY_DESCRIPTION = """## Obtener el reporte de Experian Clarity Services

En este portal no es necesario crear un usuario ni una contraseña.

1. Ingrese al portal oficial de Experian Clarity Services: [https://consumers.clarityservices.com/](https://consumers.clarityservices.com/)
2. Seleccione **ACCESS YOUR CLARITY CREDIT REPORT**.
3. Complete su información personal y responda las preguntas de seguridad para verificar su identidad.
4. Si el sistema no puede verificar su identidad automáticamente, deberá subir:
    * Una foto de su documento de identidad
    * Una factura o estado de cuenta donde aparezca su nombre y dirección actual
5. Una vez completada la verificación, podrá acceder a su reporte completo.
6. Descargue el reporte y adjúntelo en esta tarjeta.

Importante: asegúrese de que el documento esté completo y sea legible."""

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
            title=ACCOUNTS_CARD_TITLE,
            description_md=_CLIENT_TODO_ACCOUNTS_DESCRIPTION,
            position=1,
        ),
        DefaultBoardCard(
            title=BANKS_CARD_TITLE,
            description_md=_CLIENT_TODO_BANKS_DESCRIPTION,
            position=2,
        ),
        DefaultBoardCard(
            title=TAXES_CARD_TITLE,
            description_md=_CLIENT_TODO_TAXES_DESCRIPTION,
            position=3,
            requires_file_upload=True,
        ),
    ),
    "Credenciales": (
        DefaultBoardCard(
            title="Experian",
            description_md=_CREDENTIALS_EXPERIAN_DESCRIPTION,
            position=0,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title="Equifax",
            description_md=_CREDENTIALS_EQUIFAX_DESCRIPTION,
            position=1,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title="TransUnion",
            description_md=_CREDENTIALS_TRANSUNION_DESCRIPTION,
            position=2,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title="ChexSystems",
            description_md=_CREDENTIALS_CHEXSYSTEMS_DESCRIPTION,
            position=3,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title="Innovis",
            description_md=_CREDENTIALS_INNOVIS_DESCRIPTION,
            position=4,
            requires_credentials=True,
        ),
        DefaultBoardCard(
            title=CLARITY_CARD_TITLE,
            description_md=_CREDENTIALS_CLARITY_DESCRIPTION,
            position=5,
            requires_file_upload=True,
        ),
    ),
}


def default_cards_for_column(column_title: str) -> tuple[DefaultBoardCard, ...]:
    return DEFAULT_BOARD_CARDS_BY_COLUMN.get(column_title, ())


def canonical_default_card_title(title: str | None) -> str:
    normalized = (title or "").strip()
    return CARD_TITLE_ALIASES.get(normalized, normalized)


def is_taxes_card(title: str | None) -> bool:
    normalized = (title or "").strip().lower()
    return "tax" in normalized or "impuesto" in normalized


def is_optional_onboarding_card(title: str | None) -> bool:
    """Cards que no bloquean el cierre del onboarding (p. ej. taxes a pedido)."""
    return is_taxes_card(title)
