import streamlit as st 
import pandas as pd
from datetime import date, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ================== CONFIGURACIÓN GENERAL ==================

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SPREADSHEET_ID = "1tk1rm8h4ETGnmM4DwTDKGmaVnoGx-Q6MOmEcBUr5pTc"

DRIVE_SEARCH_BASE_URL = "https://drive.google.com/drive/u/0/search?q="

DRIVE_FOLDER_URL = (
    "https://drive.google.com/drive/folders/"
    "1Osdk52hINpP9c1syvGqIVGVYm4yJV0l-?usp=drive_link"
)

INITIAL_CAPITAL = 1000.0


# ================== HELPERS NUMÉRICOS ==================

def parse_number(value):
    """Convierte strings con comas/puntos a float."""
    if value is None:
        return 0.0
    s = str(value).strip()
    if s == "":
        return 0.0
    s = s.replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


# ================== GOOGLE SHEETS: CORE ==================

def get_gcp_credentials():
    return service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES,
    )


@st.cache_resource
def get_sheets_service():
    creds = get_gcp_credentials()
    return build("sheets", "v4", credentials=creds)


def ensure_sheet_exists(title: str):
    """
    Verifica que exista la pestaña "title".
    Si la API da error (permisos, etc.), NO tumba la app.
    """
    service = get_sheets_service()
    try:
        spreadsheet = service.spreadsheets().get(
            spreadsheetId=SPREADSHEET_ID
        ).execute()
        existing_titles = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]
        if title in existing_titles:
            return

        body = {"requests": [{"addSheet": {"properties": {"title": title}}}]}
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=body,
        ).execute()
    except HttpError:
        st.warning(
            f"No se pudo crear/verificar la pestaña '{title}' en Google Sheets. "
            f"Asegúrate de que existe y se llama exactamente así. "
            f"Si ya existe, puedes ignorar este aviso."
        )
    except Exception:
        # No rompemos la app por detalles de la API
        pass


def read_sheet(title: str, range_a1: str):
    service = get_sheets_service()
    try:
        resp = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{title}!{range_a1}",
        ).execute()
    except Exception:
        return []
    return resp.get("values", [])


def append_rows(title: str, rows, start_a1: str = "A1"):
    service = get_sheets_service()
    body = {"values": rows}
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{title}!{start_a1}",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()
    st.cache_data.clear()


def update_row(title: str, row_index: int, values):
    service = get_sheets_service()
    end_col = chr(ord("A") + len(values) - 1)
    range_a1 = f"{title}!A{row_index}:{end_col}{row_index}"
    body = {"values": [[str(v) for v in values]]}
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=range_a1,
        valueInputOption="USER_ENTERED",
        body=body,
    ).execute()
    st.cache_data.clear()


# ================== HELPERS BOOLEANS ==================

def _bool_to_si(value):
    return "SI" if value else "NO"


# ================== CLIENTES EN SHEETS ==================

@st.cache_data(ttl=60)
def get_clients_df():
    """
    Hoja: Clientes
    A phone
    B full_name
    C address
    D emergency_name
    E emergency_phone
    F has_12m_job (SI/NO)
    G is_recommended (SI/NO)
    H can_pay_weekly (SI/NO)
    I accepts_terms (SI/NO)
    J docs_url
    K created_at
    L rating
    """
    ensure_sheet_exists("Clientes")
    rows = read_sheet("Clientes", "A1:L")
    if not rows:
        return pd.DataFrame(
            columns=[
                "phone",
                "full_name",
                "address",
                "emergency_name",
                "emergency_phone",
                "has_12m_job",
                "is_recommended",
                "can_pay_weekly",
                "accepts_terms",
                "docs_url",
                "created_at",
                "rating",
                "row_index",
            ]
        )

    data = []
    for idx, row in enumerate(rows, start=1):
        row = row + [""] * (12 - len(row))
        (
            phone,
            full_name,
            address,
            emergency_name,
            emergency_phone,
            has_12m_job,
            is_recommended,
            can_pay_weekly,
            accepts_terms,
            docs_url,
            created_at,
            rating,
        ) = row[:12]

        try:
            rating_val = int(rating) if str(rating).strip() != "" else None
        except Exception:
            rating_val = None

        data.append(
            {
                "phone": phone,
                "full_name": full_name,
                "address": address,
                "emergency_name": emergency_name,
                "emergency_phone": emergency_phone,
                "has_12m_job": has_12m_job,
                "is_recommended": is_recommended,
                "can_pay_weekly": can_pay_weekly,
                "accepts_terms": accepts_terms,
                "docs_url": docs_url,
                "created_at": created_at,
                "rating": rating_val,
                "row_index": idx,
            }
        )

    return pd.DataFrame(data)


def upsert_client_sheet(
    full_name,
    phone,
    address,
    emergency_name,
    emergency_phone,
    docs_url,
    has_12m_job,
    is_recommended,
    can_pay_weekly,
    accepts_terms,
):
    ensure_sheet_exists("Clientes")
    df = get_clients_df()

    has_12m_job_si = _bool_to_si(bool(has_12m_job))
    is_recommended_si = _bool_to_si(bool(is_recommended))
    can_pay_weekly_si = _bool_to_si(bool(can_pay_weekly))
    accepts_terms_si = _bool_to_si(bool(accepts_terms))

    created_at = date.today().isoformat()

    existing_phones = df["phone"].astype(str).values if not df.empty else []

    if df.empty or str(phone) not in existing_phones:
        row_index = len(df) + 1
        row = [
            phone,
            full_name,
            address,
            emergency_name,
            emergency_phone,
            has_12m_job_si,
            is_recommended_si,
            can_pay_weekly_si,
            accepts_terms_si,
            docs_url,
            created_at,
            "",
        ]
        append_rows("Clientes", [row], "A1")
        return row_index
    else:
        row_info = df[df["phone"].astype(str) == str(phone)].iloc[0]
        row_index = int(row_info["row_index"])
        rating = row_info["rating"] if row_info["rating"] is not None else ""
        created_at_existing = row_info["created_at"] or created_at

        row = [
            phone,
            full_name,
            address,
            emergency_name,
            emergency_phone,
            has_12m_job_si,
            is_recommended_si,
            can_pay_weekly_si,
            accepts_terms_si,
            docs_url,
            created_at_existing,
            rating,
        ]
        update_row("Clientes", row_index, row)
        return row_index


def update_client_rating_sheet(phone: str, rating: int):
    df = get_clients_df()
    if df.empty or str(phone) not in df["phone"].astype(str).values:
        return

    row_info = df[df["phone"].astype(str) == str(phone)].iloc[0]
    row_index = int(row_info["row_index"])

    row = [
        row_info["phone"],
        row_info["full_name"],
        row_info["address"],
        row_info["emergency_name"],
        row_info["emergency_phone"],
        row_info["has_12m_job"],
        row_info["is_recommended"],
        row_info["can_pay_weekly"],
        row_info["accepts_terms"],
        row_info["docs_url"],
        row_info["created_at"] or date.today().isoformat(),
        rating,
    ]
    update_row("Clientes", row_index, row)


# ================== PRÉSTAMOS EN SHEETS ==================

@st.cache_data(ttl=60)
def get_loans_df():
    ensure_sheet_exists("Prestamos")
    rows = read_sheet("Prestamos", "A1:S")
    if not rows:
        return pd.DataFrame(
            columns=[
                "system_reg_date",
                "loan_id",
                "sequence",
                "loan_date",
                "first_due_date",
                "full_name",
                "phone",
                "address",
                "emergency_name",
                "emergency_phone",
                "has_12m_job",
                "is_recommended",
                "can_pay_weekly",
                "accepts_terms",
                "principal",
                "total_to_pay",
                "weekly_payment",
                "docs_url",
                "status",
                "row_index",
            ]
        )

    data = []
    for idx, row in enumerate(rows, start=1):
        row = row + [""] * (19 - len(row))
        (
            system_reg_date,
            loan_id_str,
            sequence_str,
            loan_date_str,
            first_due_date_str,
            full_name,
            phone,
            address,
            emergency_name,
            emergency_phone,
            has_12m_job,
            is_recommended,
            can_pay_weekly,
            accepts_terms,
            principal_str,
            total_to_pay_str,
            weekly_payment_str,
            docs_url,
            status,
        ) = row[:19]

        try:
            loan_id = int(loan_id_str) if loan_id_str else None
        except Exception:
            loan_id = None

        try:
            sequence = int(sequence_str) if sequence_str else 1
        except Exception:
            sequence = 1

        principal = parse_number(principal_str)
        if total_to_pay_str:
            total_to_pay = parse_number(total_to_pay_str)
        else:
            total_to_pay = principal * 1.5

        if weekly_payment_str:
            weekly_payment = parse_number(weekly_payment_str)
        else:
            weekly_payment = total_to_pay / 12 if total_to_pay else 0.0

        status = status or "activo"

        data.append(
            {
                "system_reg_date": system_reg_date,
                "loan_id": loan_id,
                "sequence": sequence,
                "loan_date": loan_date_str,
                "first_due_date": first_due_date_str,
                "full_name": full_name,
                "phone": phone,
                "address": address,
                "emergency_name": emergency_name,
                "emergency_phone": emergency_phone,
                "has_12m_job": has_12m_job,
                "is_recommended": is_recommended,
                "can_pay_weekly": can_pay_weekly,
                "accepts_terms": accepts_terms,
                "principal": principal,
                "total_to_pay": total_to_pay,
                "weekly_payment": weekly_payment,
                "docs_url": docs_url,
                "status": status,
                "row_index": idx,
            }
        )

    return pd.DataFrame(data)


def get_next_loan_id():
    df = get_loans_df()
    if df.empty:
        return 1
    max_id = df["loan_id"].dropna().max()
    return int(max_id) + 1 if pd.notna(max_id) else 1


def count_loans_for_phone(phone: str) -> int:
    df = get_loans_df()
    if df.empty:
        return 0
    return int((df["phone"].astype(str) == str(phone)).sum())


def get_first_due_date(loan_date: date) -> date:
    weekday = loan_date.weekday()
    days_to_this_saturday = (5 - weekday) % 7
    if days_to_this_saturday >= 3:
        first = loan_date + timedelta(days=days_to_this_saturday)
    else:
        first = loan_date + timedelta(days=days_to_this_saturday + 7)
    return first


def append_loan_to_sheet(
    loan_id,
    sequence,
    loan_date,
    first_due_date,
    full_name,
    phone,
    address,
    emergency_name,
    emergency_phone,
    has_12m_job,
    is_recommended,
    can_pay_weekly,
    accepts_terms,
    principal,
    total_to_pay,
    weekly_payment,
    docs_url,
):
    ensure_sheet_exists("Prestamos")

    system_reg_date = date.today().isoformat()
    has_12m_job_si = _bool_to_si(bool(has_12m_job))
    is_recommended_si = _bool_to_si(bool(is_recommended))
    can_pay_weekly_si = _bool_to_si(bool(can_pay_weekly))
    accepts_terms_si = _bool_to_si(bool(accepts_terms))

    row = [
        system_reg_date,
        loan_id,
        sequence,
        loan_date.isoformat(),
        first_due_date.isoformat(),
        full_name,
        phone,
        address,
        emergency_name,
        emergency_phone,
        has_12m_job_si,
        is_recommended_si,
        can_pay_weekly_si,
        accepts_terms_si,
        float(principal),
        float(total_to_pay),
        float(weekly_payment),
        docs_url or "",
        "activo",
    ]
    append_rows("Prestamos", [row], "A1")


def create_loan_sheet_for_client(
    full_name,
    phone,
    address,
    emergency_name,
    emergency_phone,
    docs_url,
    has_12m_job,
    is_recommended,
    can_pay_weekly,
    accepts_terms,
    principal,
    loan_date,
):
    interest_rate = 0.5
    weeks = 12
    total_to_pay = principal * (1 + interest_rate)
    weekly_payment = total_to_pay / weeks
    first_due = get_first_due_date(loan_date)

    prev_loans = count_loans_for_phone(phone)
    sequence = prev_loans + 1

    loan_id = get_next_loan_id()

    append_loan_to_sheet(
        loan_id=loan_id,
        sequence=sequence,
        loan_date=loan_date,
        first_due_date=first_due,
        full_name=full_name,
        phone=phone,
        address=address,
        emergency_name=emergency_name,
        emergency_phone=emergency_phone,
        has_12m_job=has_12m_job,
        is_recommended=is_recommended,
        can_pay_weekly=can_pay_weekly,
        accepts_terms=accepts_terms,
        principal=principal,
        total_to_pay=total_to_pay,
        weekly_payment=weekly_payment,
        docs_url=docs_url,
    )

    return loan_id, weekly_payment, total_to_pay, sequence, first_due


def search_loans_by_client(text: str):
    df = get_loans_df()
    if df.empty:
        return df

    mask = df["phone"].astype(str).str.contains(text, case=False, na=False) | \
           df["full_name"].astype(str).str.contains(text, case=False, na=False)
    return df[mask].sort_values("loan_id", ascending=False)


def get_loan_from_sheet(loan_id: int):
    loans_df = get_loans_df()
    if loans_df.empty or loan_id not in loans_df["loan_id"].values:
        return None

    row = loans_df[loans_df["loan_id"] == loan_id].iloc[0]

    clients_df = get_clients_df()
    rating = None
    if not clients_df.empty and row["phone"] in clients_df["phone"].values:
        rating = clients_df[clients_df["phone"] == row["phone"]].iloc[0]["rating"]

    loan_dict = row.to_dict()
    loan_dict["rating"] = rating
    return loan_dict


def get_all_loans_with_status(status_filter=None):
    df = get_loans_df()
    if df.empty:
        return df
    if status_filter:
        df = df[df["status"] == status_filter]
    return df.sort_values("loan_id", ascending=False)


# ================== PAGOS EN SHEETS ==================

@st.cache_data(ttl=60)
def get_payments_df():
    """
    Hoja: Pagos

    NUEVO FORMATO:
    A created_at
    B loan_id
    C phone
    D full_name
    E payment_date
    F amount

    COMPATIBLE con registros viejos de 4 columnas.
    """
    ensure_sheet_exists("Pagos")
    rows = read_sheet("Pagos", "A1:F")
    if not rows:
        return pd.DataFrame(
            columns=["created_at", "loan_id", "phone", "full_name", "payment_date", "amount"]
        )

    data = []
    for row in rows:
        if len(row) >= 6:
            row = row + [""] * (6 - len(row))
            created_at, loan_id_str, phone, full_name, payment_date_str, amount_str = row[:6]
        else:
            row = row + [""] * (4 - len(row))
            created_at, loan_id_str, payment_date_str, amount_str = row[:4]
            phone = ""
            full_name = ""

        try:
            loan_id = int(loan_id_str) if loan_id_str else None
        except Exception:
            loan_id = None

        amount = parse_number(amount_str)

        data.append(
            {
                "created_at": created_at,
                "loan_id": loan_id,
                "phone": phone,
                "full_name": full_name,
                "payment_date": payment_date_str,
                "amount": amount,
            }
        )

    return pd.DataFrame(data)


def get_payments_for_loan(loan_id: int):
    df = get_payments_df()
    if df.empty:
        return pd.DataFrame(columns=df.columns)
    return df[df["loan_id"] == loan_id].sort_values("payment_date")


def append_payment(loan_id: int, payment_date: date, amount: float, phone: str, full_name: str):
    ensure_sheet_exists("Pagos")
    row = [
        date.today().isoformat(),
        loan_id,
        phone,
        full_name,
        payment_date.isoformat(),
        float(amount),
    ]
    append_rows("Pagos", [row], "A1")


def update_loan_status_if_paid_sheet(loan_id: int):
    loans_df = get_loans_df()
    if loans_df.empty or loan_id not in loans_df["loan_id"].values:
        return

    row = loans_df[loans_df["loan_id"] == loan_id].iloc[0]
    total_to_pay = float(row["total_to_pay"])
    payments_df = get_payments_df()
    if payments_df.empty:
        return

    total_paid = payments_df[payments_df["loan_id"] == loan_id]["amount"].sum()
    if total_paid >= total_to_pay - 0.01:
        row_index = int(row["row_index"])
        updated_values = [
            row["system_reg_date"],
            row["loan_id"],
            row["sequence"],
            row["loan_date"],
            row["first_due_date"],
            row["full_name"],
            row["phone"],
            row["address"],
            row["emergency_name"],
            row["emergency_phone"],
            row["has_12m_job"],
            row["is_recommended"],
            row["can_pay_weekly"],
            row["accepts_terms"],
            row["principal"],
            row["total_to_pay"],
            row["weekly_payment"],
            row["docs_url"],
            "cerrado",
        ]
        update_row("Prestamos", row_index, updated_values)


# ================== GASTOS EN SHEETS ==================

@st.cache_data(ttl=60)
def get_expenses_df():
    ensure_sheet_exists("Gastos")
    rows = read_sheet("Gastos", "A1:E")
    if not rows:
        return pd.DataFrame(
            columns=["created_at", "expense_date", "amount", "category", "notes"]
        )

    data = []
    for row in rows:
        row = row + [""] * (5 - len(row))
        created_at, expense_date_str, amount_str, category, notes = row[:5]
        amount = parse_number(amount_str)
        data.append(
            {
                "created_at": created_at,
                "expense_date": expense_date_str,
                "amount": amount,
                "category": category,
                "notes": notes,
            }
        )
    return pd.DataFrame(data)


def append_expense(expense_date: date, amount: float, category: str, notes: str):
    ensure_sheet_exists("Gastos")
    row = [
        date.today().isoformat(),
        expense_date.isoformat(),
        float(amount),
        category,
        notes,
    ]
    append_rows("Gastos", [row], "A1")


# ================== RESUMEN FINANCIERO ==================

def get_financial_summary(initial_capital: float = INITIAL_CAPITAL):
    clients_df = get_clients_df()
    loans_df = get_loans_df()
    payments_df = get_payments_df()
    expenses_df = get_expenses_df()

    clientes_registrados = len(clients_df)
    creditos_activos = len(loans_df[loans_df["status"] == "activo"]) if not loans_df.empty else 0
    creditos_cerrados = len(loans_df[loans_df["status"] == "cerrado"]) if not loans_df.empty else 0

    monto_total_prestado = loans_df["principal"].sum() if not loans_df.empty else 0.0
    total_a_cobrar = loans_df["total_to_pay"].sum() if not loans_df.empty else 0.0
    total_cobrado = payments_df["amount"].sum() if not payments_df.empty else 0.0
    total_gastos_operativos = expenses_df["amount"].sum() if not expenses_df.empty else 0.0

    intereses_teoricos = total_a_cobrar - monto_total_prestado
    monto_pendiente_por_recaudar = total_a_cobrar - total_cobrado

    saldo_efectivo = (
        initial_capital
        - monto_total_prestado
        + total_cobrado
        - total_gastos_operativos
    )
    saldo_total_cuenta = saldo_efectivo + monto_pendiente_por_recaudar

    return {
        "clientes_registrados": int(clientes_registrados),
        "creditos_activos": int(creditos_activos),
        "creditos_cerrados": int(creditos_cerrados),
        "monto_total_prestado": float(monto_total_prestado),
        "intereses_teoricos": float(intereses_teoricos),
        "total_cobrado": float(total_cobrado),
        "monto_pendiente_por_recaudar": float(monto_pendiente_por_recaudar),
        "saldo_efectivo": float(saldo_efectivo),
        "saldo_total_cuenta": float(saldo_total_cuenta),
        "total_gastos_operativos": float(total_gastos_operativos),
        "total_a_cobrar": float(total_a_cobrar),
    }


# ================== UI HELPERS: TARJETAS KPI ==================

def render_kpi_card(title, value, icon, bg_color, growth_pct=None, growth_label=""):
    # Ya no usamos growth_pct / growth_label, pero los dejamos opcionales
    card_html = f"""
    <div style="
        background:{bg_color};
        border-radius:14px;
        padding:10px 12px;
        height:100%;
        border:1px solid rgba(255,255,255,0.08);
        display:flex;
        flex-direction:column;
        justify-content:space-between;
    ">
        <div style="display:flex; align-items:center; justify-content:space-between;">
            <div style="font-size:0.75rem; color:#cfd8e3; font-weight:500;">
                {title}
            </div>
            <div style="font-size:1rem;">
                {icon}
            </div>
        </div>
        <div style="margin-top:4px; font-size:1.1rem; font-weight:700; color:white;">
            {value}
        </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


# ================== PÁGINAS: REGISTRO (WIZARD) ==================

def page_registro():
    st.subheader("Registro de crédito")

    if "wizard_step" not in st.session_state:
        st.session_state["wizard_step"] = 1
    if "wizard_data" not in st.session_state:
        st.session_state["wizard_data"] = {}

    step = st.session_state["wizard_step"]
    wizard_data = st.session_state["wizard_data"]

    st.progress(step / 3)
    st.caption(f"Paso {step} de 3")

    # ----- PASO 1 -----
    if step == 1:
        st.markdown("### Paso 1: Precalificación")

        with st.form("form_precal"):
            principal = st.number_input(
                "Monto del crédito solicitado",
                min_value=0.0,
                step=50.0,
                value=float(wizard_data.get("principal", 0.0)),
            )

            has_12m_job = st.checkbox(
                "Tiene más de 12 meses en el trabajo actual",
                value=wizard_data.get("has_12m_job", False),
            )
            is_recommended = st.checkbox(
                "Es recomendado de alguien que conozcamos",
                value=wizard_data.get("is_recommended", False),
            )
            can_pay_weekly = st.checkbox(
                "Puede pagar semanalmente la cuota establecida",
                value=wizard_data.get("can_pay_weekly", False),
            )
            accepts_terms = st.checkbox(
                "Está de acuerdo con el valor de su pago y condiciones del crédito",
                value=wizard_data.get("accepts_terms", False),
            )

            loan_date = st.date_input(
                "Fecha del préstamo",
                value=wizard_data.get("loan_date", date.today()),
            )

            submitted_precal = st.form_submit_button("Ver precalificación")

        if submitted_precal:
            if principal <= 0:
                st.error("Debes capturar un monto de crédito mayor a 0.")
            elif not (has_12m_job and is_recommended and can_pay_weekly and accepts_terms):
                st.error(
                    "El cliente no cumple con todos los criterios de precalificación. "
                    "Revisa las respuestas del check."
                )
            else:
                interest_rate = 0.5
                weeks = 12
                total_to_pay = principal * (1 + interest_rate)
                weekly_payment = total_to_pay / weeks
                first_due = get_first_due_date(loan_date)

                wizard_data.update({
                    "principal": principal,
                    "has_12m_job": has_12m_job,
                    "is_recommended": is_recommended,
                    "can_pay_weekly": can_pay_weekly,
                    "accepts_terms": accepts_terms,
                    "loan_date": loan_date,
                    "precal_ok": True,
                    "precal_total_to_pay": total_to_pay,
                    "precal_weekly_payment": weekly_payment,
                    "precal_first_due": first_due.isoformat(),
                })
                st.session_state["wizard_data"] = wizard_data

        if wizard_data.get("precal_ok"):
            principal = wizard_data["principal"]
            total_to_pay = wizard_data["precal_total_to_pay"]
            weekly_payment = wizard_data["precal_weekly_payment"]
            first_due = date.fromisoformat(wizard_data["precal_first_due"])

            texto_precal = (
                f"Monto solicitado: ${principal:,.2f}\n\n"
                f"Total a pagar (50% interés): ${total_to_pay:,.2f}\n\n"
                "Plazo: 12 semanas\n\n"
                f"Pago semanal estimado: ${weekly_payment:,.2f}\n\n"
                f"Primer pago programado para el sábado: {first_due.strftime('%Y-%m-%d')}"
            )
            st.success("Precalificación aprobada.")
            st.info(texto_precal)

            if st.button(
                "Continuar al Paso 2 (cliente acepta continuar)",
                key="btn_to_step2",
                use_container_width=True,
            ):
                st.session_state["wizard_step"] = 2
                st.rerun()

    # ----- PASO 2 -----
    elif step == 2:
        st.markdown("### Paso 2: Datos del cliente")

        if not wizard_data.get("precal_ok"):
            st.warning("Primero completa la precalificación (Paso 1).")
            if st.button("Volver al Paso 1", use_container_width=True):
                st.session_state["wizard_step"] = 1
                st.rerun()
            return

        with st.form("form_datos_cliente"):
            full_name = st.text_input(
                "Nombre completo",
                value=wizard_data.get("full_name", ""),
            )
            phone = st.text_input(
                "Teléfono (llave única)",
                value=wizard_data.get("phone", ""),
            )
            address = st.text_area(
                "Dirección",
                value=wizard_data.get("address", ""),
            )
            emergency_name = st.text_input(
                "Nombre contacto de emergencia",
                value=wizard_data.get("emergency_name", ""),
            )
            emergency_phone = st.text_input(
                "Teléfono contacto de emergencia",
                value=wizard_data.get("emergency_phone", ""),
            )

            col_a, col_b = st.columns(2)
            with col_a:
                btn_volver = st.form_submit_button("⬅️ Volver al Paso 1")
            with col_b:
                btn_siguiente = st.form_submit_button("Continuar al Paso 3 ➡️")

        if btn_volver:
            st.session_state["wizard_step"] = 1
            st.rerun()

        if btn_siguiente:
            if not phone:
                st.error("Debes capturar al menos el teléfono del cliente.")
            else:
                wizard_data.update({
                    "full_name": full_name,
                    "phone": phone,
                    "address": address,
                    "emergency_name": emergency_name,
                    "emergency_phone": emergency_phone,
                })
                st.session_state["wizard_data"] = wizard_data
                st.session_state["wizard_step"] = 3
                st.rerun()

    # ----- PASO 3 -----
    elif step == 3:
        st.markdown("### Paso 3: Subida de archivos y confirmación")

        if "phone" not in wizard_data:
            st.warning("Primero completa los datos del cliente (Paso 2).")
            if st.button("Volver al Paso 2", use_container_width=True):
                st.session_state["wizard_step"] = 2
                st.rerun()
            return

        phone = wizard_data["phone"]
        docs_url = f"{DRIVE_SEARCH_BASE_URL}{phone}"

        st.markdown("#### Instrucciones para documentos")
        st.write(
            "Sube los documentos (ID, bill o comprobante de domicilio, etc.) "
            "directamente en tu Google Drive."
        )

        st.markdown(
            f"""
            <a href="{DRIVE_FOLDER_URL}" target="_blank">
                <button style="padding:12px 16px; border-radius:8px; border:none;
                               background-color:#0f9d58; color:white; cursor:pointer;
                               width:100%; font-weight:600;">
                    Cargar imágenes en carpeta de Drive
                </button>
            </a>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            También puedes usar este enlace para buscar rápidamente los documentos
            de este cliente por teléfono en Drive:

            👉 [Buscar documentos en Drive para {phone}]({docs_url})
            """
        )

        with st.form("form_confirmar"):
            docs_ok = st.checkbox(
                "Confirmo que ya subí los documentos del cliente a Google Drive "
                "y están identificados por su teléfono."
            )

            col1, col2 = st.columns(2)
            with col1:
                btn_volver = st.form_submit_button("⬅️ Volver al Paso 2")
            with col2:
                btn_guardar = st.form_submit_button("✅ Guardar cliente y crédito")

        if btn_volver:
            st.session_state["wizard_step"] = 2
            st.rerun()

        if btn_guardar:
            if not docs_ok:
                st.error("Marca la casilla de confirmación de documentos para continuar.")
                return

            principal = float(wizard_data["principal"])
            loan_date = wizard_data["loan_date"]
            has_12m_job = bool(wizard_data["has_12m_job"])
            is_recommended = bool(wizard_data["is_recommended"])
            can_pay_weekly = bool(wizard_data["can_pay_weekly"])
            accepts_terms = bool(wizard_data["accepts_terms"])

            full_name = wizard_data["full_name"]
            phone = wizard_data["phone"]
            address = wizard_data["address"]
            emergency_name = wizard_data["emergency_name"]
            emergency_phone = wizard_data["emergency_phone"]

            upsert_client_sheet(
                full_name=full_name,
                phone=phone,
                address=address,
                emergency_name=emergency_name,
                emergency_phone=emergency_phone,
                docs_url=docs_url,
                has_12m_job=has_12m_job,
                is_recommended=is_recommended,
                can_pay_weekly=can_pay_weekly,
                accepts_terms=accepts_terms,
            )

            loan_id, weekly_payment, total_to_pay, sequence, first_due = create_loan_sheet_for_client(
                full_name=full_name,
                phone=phone,
                address=address,
                emergency_name=emergency_name,
                emergency_phone=emergency_phone,
                docs_url=docs_url,
                has_12m_job=has_12m_job,
                is_recommended=is_recommended,
                can_pay_weekly=can_pay_weekly,
                accepts_terms=accepts_terms,
                principal=principal,
                loan_date=loan_date,
            )

            st.success("Cliente y crédito registrados correctamente.")

            texto_resumen = (
                f"Crédito #{sequence} para este cliente\n\n"
                f"Nombre: {full_name} | Teléfono: {phone}\n\n"
                f"Monto prestado: ${principal:,.2f}\n"
                f"Total a pagar (50% interés): ${total_to_pay:,.2f}\n"
                "Plazo: 12 semanas\n"
                f"Pago semanal: ${weekly_payment:,.2f}\n"
                f"Primer pago programado para el sábado: {first_due.strftime('%Y-%m-%d')}"
            )
            st.info(texto_resumen)

            st.markdown(
                f"[Ver / buscar documentos en Drive para {phone}]({docs_url})"
            )

            if st.button("Registrar otro crédito", key="btn_new_loan", use_container_width=True):
                st.session_state["wizard_step"] = 1
                st.session_state["wizard_data"] = {}
                st.rerun()


# ================== PÁGINAS: CLIENTES ==================

def page_clientes():
    st.subheader("Base de clientes")

    df = get_clients_df()
    if df.empty:
        st.info("No hay clientes registrados.")
        return

    cols = ["full_name", "phone", "address", "emergency_name", "emergency_phone", "rating"]
    show_cols = [c for c in cols if c in df.columns]
    st.dataframe(
        df[show_cols],
        use_container_width=True,
        hide_index=True,
    )


# ================== PÁGINAS: CRÉDITOS ==================

def page_creditos_activos():
    st.subheader("Créditos activos")

    df = get_all_loans_with_status("activo")
    if df.empty:
        st.info("No hay créditos activos.")
        return

    show_cols = [
        "loan_id",
        "sequence",
        "full_name",
        "phone",
        "loan_date",
        "first_due_date",
        "principal",
        "total_to_pay",
        "weekly_payment",
        "status",
    ]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)


def page_historial():
    st.subheader("Historial de créditos (cerrados)")

    df = get_all_loans_with_status("cerrado")
    if df.empty:
        st.info("No hay créditos cerrados todavía.")
        return

    show_cols = [
        "loan_id",
        "sequence",
        "full_name",
        "phone",
        "loan_date",
        "first_due_date",
        "principal",
        "total_to_pay",
        "weekly_payment",
        "status",
    ]
    st.dataframe(df[show_cols], use_container_width=True, hide_index=True)


# ================== PÁGINAS: REGISTRAR PAGO ==================

def page_registrar_pago():
    st.subheader("Registrar pago semanal")

    search_text = st.text_input(
        "Buscar cliente por nombre o teléfono:",
        key="search_pago"
    )
    if not search_text:
        st.info("Escribe al menos parte del nombre o teléfono para buscar.")
        return

    loans_df = search_loans_by_client(search_text)
    if loans_df.empty:
        st.warning("No se encontraron créditos para ese criterio.")
        return

    st.markdown("#### Créditos encontrados")
    show_cols = [
        "loan_id",
        "sequence",
        "full_name",
        "phone",
        "loan_date",
        "first_due_date",
        "principal",
        "total_to_pay",
        "weekly_payment",
        "status",
    ]
    st.dataframe(loans_df[show_cols], use_container_width=True, hide_index=True)

    loan_ids = loans_df["loan_id"].tolist()
    selected_loan_id = st.selectbox(
        "Selecciona el crédito",
        loan_ids,
        format_func=lambda x: f"Crédito #{x}",
    )

    loan = get_loan_from_sheet(selected_loan_id)
    if loan is None:
        st.error("No se pudo cargar el crédito.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Cliente**")
        st.write(f"Nombre: {loan['full_name']}")
        st.write(f"Teléfono: {loan['phone']}")
        st.write(f"Dirección: {loan['address']}")

    with col2:
        st.markdown("**Crédito**")
        st.write(f"Número de crédito para este cliente: {loan.get('sequence', 'N/A')}")
        st.write(f"Fecha del préstamo: {loan['loan_date']}")
        st.write(f"Primer pago (sábado): {loan.get('first_due_date', '')}")
        st.write(f"Monto: ${loan['principal']:,.2f}")
        st.write(f"Total a pagar: ${loan['total_to_pay']:,.2f}")
        st.write(f"Pago semanal: ${loan['weekly_payment']:,.2f}")
        st.write(f"Estado: {loan['status']}")

    st.markdown("---")
    st.subheader("Calificación del cliente")

    current_rating = loan["rating"]
    if isinstance(current_rating, (int, float)) and not pd.isna(current_rating):
        slider_default = int(current_rating)
    else:
        slider_default = 3

    new_rating = st.slider(
        "Calificación (1 a 5 estrellas)",
        min_value=1,
        max_value=5,
        value=slider_default,
        help="Evalúa qué tan puntual y cumplido ha sido este cliente con sus pagos.",
    )

    if st.button("Guardar calificación del cliente", key="btn_save_rating"):
        update_client_rating_sheet(loan["phone"], new_rating)
        st.success("Calificación del cliente actualizada.")

    payments_df = get_payments_for_loan(selected_loan_id)
    total_pagado = payments_df["amount"].sum() if not payments_df.empty else 0.0
    restante = loan["total_to_pay"] - total_pagado

    weeks = 12
    num_payments = len(payments_df)
    pagos_pendientes = max(weeks - num_payments, 0)

    first_due_str = loan.get("first_due_date", None)
    if first_due_str:
        first_due_date = date.fromisoformat(first_due_str)
        fecha_final = first_due_date + timedelta(days=7 * (weeks - 1))
        fecha_final_str = fecha_final.strftime("%Y-%m-%d")
    else:
        fecha_final_str = "N/A"

    st.subheader("Resumen de pagos")
    st.write(f"Pagos registrados: {num_payments}")
    st.write(f"Pagos pendientes: {pagos_pendientes}")
    st.write(f"Fecha de finalización de pagos: {fecha_final_str}")
    st.write(f"Total pagado: ${total_pagado:,.2f}")
    st.write(f"Saldo pendiente: ${restante:,.2f}")

    if not payments_df.empty:
        st.dataframe(
            payments_df[["payment_date", "amount"]],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Nuevo pago")
    with st.form("form_pago"):
        pago_ok = st.checkbox("Pago semanal recibido")
        payment_date = st.date_input("Fecha del pago", value=date.today())
        amount = float(loan["weekly_payment"])
        submitted = st.form_submit_button("Guardar pago")

    if submitted:
        if not pago_ok:
            st.error("Debes marcar el check de pago recibido.")
            return

        append_payment(selected_loan_id, payment_date, amount, loan["phone"], loan["full_name"])
        update_loan_status_if_paid_sheet(selected_loan_id)
        st.success(f"Pago de ${amount:,.2f} registrado.")
        st.rerun()


# ================== PÁGINAS: CALENDARIO ==================

def page_calendario():
    st.subheader("Calendario de pagos")

    search_text = st.text_input(
        "Buscar cliente por nombre o teléfono:",
        key="search_calendario"
    )
    if not search_text:
        st.info("Escribe al menos parte del nombre o teléfono para buscar.")
        return

    loans_df = search_loans_by_client(search_text)
    if loans_df.empty:
        st.warning("No se encontraron créditos para ese criterio.")
        return

    st.markdown("#### Créditos encontrados")
    show_cols = [
        "loan_id",
        "sequence",
        "full_name",
        "phone",
        "loan_date",
        "first_due_date",
        "principal",
        "total_to_pay",
        "weekly_payment",
        "status",
    ]
    st.dataframe(loans_df[show_cols], use_container_width=True, hide_index=True)

    loan_ids = loans_df["loan_id"].tolist()
    selected_loan_id = st.selectbox(
        "Selecciona el crédito para ver su calendario",
        loan_ids,
        format_func=lambda x: f"Crédito #{x}",
    )

    loan = get_loan_from_sheet(selected_loan_id)
    if loan is None:
        st.error("No se pudo cargar el crédito.")
        return

    st.markdown(
        f"**Cliente:** {loan['full_name']} ({loan['phone']})  |  "
        f"Crédito #{loan.get('sequence', 'N/A')}"
    )
    st.write(f"Fecha del préstamo: {loan['loan_date']}")
    st.write(f"Primer pago (sábado): {loan.get('first_due_date', '')}")
    st.write(f"Pago semanal: ${loan['weekly_payment']:,.2f}")

    weeks = 12
    weekly_payment = float(loan["weekly_payment"])
    first_due_str = loan.get("first_due_date", None)
    if not first_due_str:
        st.error("El crédito no tiene 'first_due_date' registrado.")
        return
    first_due_date = date.fromisoformat(first_due_str)

    payments_df = get_payments_for_loan(selected_loan_id)
    num_payments = len(payments_df)

    schedule = []
    for i in range(weeks):
        due_date = first_due_date + timedelta(days=7 * i)
        status = "Pagado" if i < num_payments else "Pendiente"
        schedule.append({
            "Número de pago": i + 1,
            "Fecha programada": due_date.isoformat(),
            "Monto": weekly_payment,
            "Estado": status,
        })

    schedule_df = pd.DataFrame(schedule)

    def highlight_row(row):
        if row["Estado"] == "Pagado":
            return ["background-color: #2e7d32; color: white;"] * len(row)
        return [""] * len(row)

    styled = schedule_df.style.apply(highlight_row, axis=1)

    st.subheader("Calendario de pagos programados")
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ================== PÁGINAS: GASTOS ==================

def page_gastos():
    st.subheader("Gastos operativos")

    with st.form("form_gasto"):
        expense_date = st.date_input("Fecha del gasto", value=date.today())
        amount = st.number_input("Monto del gasto", min_value=0.0, step=10.0)
        category = st.selectbox(
            "Concepto",
            ["Marketing", "Nómina", "Gasolina", "Premios", "Descuentos", "Otro"],
        )
        notes = st.text_input("Detalle / comentario (opcional)")

        submitted = st.form_submit_button("Guardar gasto operativo")

    if submitted:
        if amount <= 0:
            st.error("El monto del gasto debe ser mayor a 0.")
        else:
            append_expense(expense_date, amount, category, notes)
            st.success("Gasto operativo registrado correctamente.")

    st.markdown("---")
    st.markdown("#### Historial de gastos operativos")

    expenses_df = get_expenses_df()
    if expenses_df.empty:
        st.info("No hay gastos operativos registrados.")
    else:
        st.dataframe(
            expenses_df[["expense_date", "amount", "category", "notes"]],
            use_container_width=True,
            hide_index=True,
        )


# ================== PÁGINAS: DASHBOARD FINANCIERO ==================

def page_financiera():
    st.subheader("Dashboard financiero")

    summary = get_financial_summary(INITIAL_CAPITAL)

    # ===== KPIs numéricos (separados de las tarjetas) =====
    st.markdown("##### KPIs principales")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Clientes registrados", summary["clientes_registrados"])
    with c2:
        st.metric("Créditos activos", summary["creditos_activos"])
    with c3:
        st.metric("Créditos cerrados", summary["creditos_cerrados"])

    c4, c5, c6 = st.columns(3)
    with c4:
        st.metric("Cartera prestada", f"${summary['monto_total_prestado']:,.2f}")
    with c5:
        st.metric("Total cobrado", f"${summary['total_cobrado']:,.2f}")
    with c6:
        st.metric("Pendiente por recaudar", f"${summary['monto_pendiente_por_recaudar']:,.2f}")

    # ===== Tarjetas visuales de resumen =====
    st.markdown("##### Resumen visual")

    col1, col2 = st.columns(2)
    with col1:
        render_kpi_card(
            "Intereses teóricos",
            f"${summary['intereses_teoricos']:,.2f}",
            "📈",
            "#4a044e",
        )
    with col2:
        render_kpi_card(
            "Gastos operativos acumulados",
            f"${summary['total_gastos_operativos']:,.2f}",
            "💸",
            "#7f1d1d",
        )

    col3, col4 = st.columns(2)
    with col3:
        render_kpi_card(
            "Saldo en efectivo (caja)",
            f"${summary['saldo_efectivo']:,.2f}",
            "🧾",
            "#14532d",
        )
    with col4:
        render_kpi_card(
            "Saldo total de la cuenta",
            f"${summary['saldo_total_cuenta']:,.2f}",
            "📊",
            "#1e293b",
        )

    # KPI extra de ratio cobrado (no comparativo, solo indicador)
    ratio_cobrado = (
        summary["total_cobrado"] / summary["total_a_cobrar"] * 100
        if summary["total_a_cobrar"] > 0 else 0
    )
    st.markdown("##### Indicador de recuperación")
    render_kpi_card(
        "Cobrado vs total a cobrar",
        f"{ratio_cobrado:.1f}%",
        "✅",
        "#0f172a",
    )


# ================== MAIN ==================

def main():
    st.set_page_config(
        page_title="The Lemonade Cash",
        page_icon="🍋",
        layout="wide",
    )

    for title in ["Prestamos", "Clientes", "Pagos", "Gastos"]:
        ensure_sheet_exists(title)

    st.markdown(
        """
        <h1 style="text-align:center; margin-bottom: 0;">🍋 The Lemonade Cash</h1>
        <p style="text-align:center; margin-top: 0; color:#999;">Estamos ahí</p>
        """,
        unsafe_allow_html=True,
    )

    if "main_section" not in st.session_state:
        st.session_state["main_section"] = "clientes"

    col1, col2 = st.columns(2)
    with col1:
        if st.button("👥\nClientes", use_container_width=True):
            st.session_state["main_section"] = "clientes"
    with col2:
        if st.button("💳\nCréditos", use_container_width=True):
            st.session_state["main_section"] = "creditos"

    col3, col4 = st.columns(2)
    with col3:
        if st.button("💸\nGastos", use_container_width=True):
            st.session_state["main_section"] = "gastos"
    with col4:
        if st.button("📊\nDashboard", use_container_width=True):
            st.session_state["main_section"] = "dashboard"

    st.markdown("---")

    section = st.session_state["main_section"]

    if section == "clientes":
        tabs = st.tabs(["Registro", "Clientes", "Registrar pago"])
        with tabs[0]:
            page_registro()
        with tabs[1]:
            page_clientes()
        with tabs[2]:
            page_registrar_pago()

    elif section == "creditos":
        tabs = st.tabs(["Créditos activos", "Historial", "Calendario de pagos"])
        with tabs[0]:
            page_creditos_activos()
        with tabs[1]:
            page_historial()
        with tabs[2]:
            page_calendario()

    elif section == "gastos":
        tabs = st.tabs(["Gastos operativos"])
        with tabs[0]:
            page_gastos()

    elif section == "dashboard":
        tabs = st.tabs(["Finanzas"])
        with tabs[0]:
            page_financiera()


if __name__ == "__main__":
    main()
