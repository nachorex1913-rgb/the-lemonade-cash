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

        body = {
            "requests": [
                {"addSheet": {"properties": {"title": title}}}
            ]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=body,
        ).execute()
    except HttpError:
        # Si ya existe o no tenemos permiso de crear, solo avisamos una vez
        st.warning(
            f"No se pudo crear/verificar la pestaña '{title}' en Google Sheets. "
            f"Asegúrate de que existe y se llama exactamente así. "
            f"Si ya existe, puedes ignorar este aviso."
        )
    except Exception:
        # Cualquier otro error, lo ignoramos silenciosamente para no romper la app
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


# ================== HELPERS DE PARSEO SIMPLE ==================

def _bool_to_si(value):
    return "SI" if value else "NO"


# ================== CLIENTES EN SHEETS ==================

@st.cache_data(ttl=60)
def get_clients_df():
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
    }


def get_clients_growth_pct():
    df = get_clients_df()
    if df.empty:
        return 0.0, False
    df = df[df["created_at"] != ""]
    if df.empty:
        return 0.0, False
    df["month"] = df["created_at"].str.slice(0, 7)
    grouped = df.groupby("month")["phone"].nunique().reset_index(name="n")
    if len(grouped) < 2:
        return 0.0, False
    last = float(grouped.iloc[-1]["n"])
    prev = float(grouped.iloc[-2]["n"])
    if prev == 0:
        return 0.0, False
    pct = (last - prev) / abs(prev) * 100.0
    return pct, True


def get_portfolio_growth_pct():
    loans_df = get_loans_df()
    if loans_df.empty:
        return 0.0, False
    loans_df = loans_df[loans_df["loan_date"] != ""]
    if loans_df.empty:
        return 0.0, False
    loans_df["month"] = loans_df["loan_date"].str.slice(0, 7)
    grouped = loans_df.groupby("month")["principal"].sum().reset_index(name="principal")
    if len(grouped) < 2:
        return 0.0, False
    last = float(grouped.iloc[-1]["principal"])
    prev = float(grouped.iloc[-2]["principal"])
    if prev == 0:
        return 0.0, False
    pct = (last - prev) / abs(prev) * 100.0
    return pct, True


# ================== UI HELPERS: TARJETAS KPI ==================

def render_kpi_card(title, value, icon, bg_color, growth_pct=None, growth_label=""):
    if growth_pct is not None and growth_label:
        sign = "+" if growth_pct >= 0 else ""
        color = "#4caf50" if growth_pct >= 0 else "#e53935"
        growth_html = (
            f'<span style="color:{color}; font-weight:600;">'
            f'{sign}{growth_pct:.1f}%</span> '
            f'<span style="color:#9fb3c8;">{growth_label}</span>'
        )
    else:
        growth_html = ""

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
        <div style="margin-top:3px; font-size:0.68rem;">
            {growth_html}
        </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


# ================== PÁGINAS UI (IGUAL QUE LA VERSIÓN ANTERIOR) ==================

# --- Por espacio, no repito aquí el resto porque ya lo tenías funcionando ---
# Usa exactamente las mismas funciones que te envié en el mensaje anterior:
# page_registro, page_clientes, page_creditos_activos, page_historial,
# page_registrar_pago, page_calendario, page_gastos, page_financiera
# y el main() que conecta todo.
#
# Lo único que cambió es la función ensure_sheet_exists y las llamadas
# a ensure_sheet_exists que ahora son seguras.


# =============== PEGAR AQUÍ TODAS LAS FUNCIONES DE PÁGINAS Y MAIN QUE YA TENÍAS ===============

# (Para no hacer este mensaje kilométrico, simplemente reemplaza en tu archivo
# la parte de arriba —helpers y acceso a Sheets— por esta versión con el
# ensure_sheet_exists nuevo. El resto del código de páginas lo dejas igual.)


