import streamlit as st
import sqlite3
import pandas as pd
from datetime import date

from google.oauth2 import service_account
from googleapiclient.discovery import build

DB_NAME = "lemonade_cash.db"

# ======== CONFIG GCP (SOLO Sheets, Drive desactivado) ========

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    # "https://www.googleapis.com/auth/drive.file",  # reservado para futuro
]

def get_gcp_credentials():
    """Credenciales desde Streamlit Secrets (service account)."""
    return service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES,
    )


@st.cache_resource
def get_sheets_service():
    creds = get_gcp_credentials()
    return build("sheets", "v4", credentials=creds)


def append_loan_to_sheet(
    loan_id,
    loan_date,
    principal,
    total_to_pay,
    weekly_payment,
    full_name,
    phone,
    address,
    emergency_name,
    emergency_phone,
    has_12m_job,
    is_recommended,
    can_pay_weekly,
    accepts_terms,
    domicilio_url,
    id_url,
):
    """
    Agrega una fila a Google Sheets con datos del crédito.
    Aquí usamos el ID de la hoja directamente para evitar problemas con secrets.
    """

    # 🔒 ID fijo de tu Google Sheet (el que me pasaste)
    spreadsheet_id = "1tk1rm8h4ETGnmM4DwTDKGmaVnoGx-Q6MOmEcBUr5pTc"

    service = get_sheets_service()

    def yes_no(v):
        return "SI" if v else "NO"

    values = [[
        str(date.today()),               # Fecha de registro en el sistema
        loan_id,                         # ID interno
        loan_date.isoformat(),           # Fecha del préstamo
        full_name,
        phone,
        address,
        emergency_name,
        emergency_phone,
        yes_no(has_12m_job),
        yes_no(is_recommended),
        yes_no(can_pay_weekly),
        yes_no(accepts_terms),
        float(principal),
        float(total_to_pay),
        float(weekly_payment),
        domicilio_url or "",
        id_url or "",
    ]]

    body = {"values": values}

    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range="Prestamos!A1",  # pestaña "Prestamos" en tu Google Sheet
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()


def save_uploaded_file_to_drive(uploaded_file, prefix):
    """
    Stub actual: NO sube a Google Drive porque las Service Accounts
    sin unidad compartida no tienen cuota de almacenamiento.

    Mantiene la interfaz (no rompe la app) y devuelve None.
    En el futuro, cuando uses una Unidad Compartida de Workspace,
    aquí reactivamos el código de subida.
    """
    if uploaded_file is None:
        return None

    st.warning(
        "Nota: el archivo se recibió, pero no se está subiendo a Google Drive "
        "porque la Service Account no tiene cuota de almacenamiento. "
        "Más adelante se puede activar usando una Unidad Compartida de Workspace."
    )

    return None


# ========= BASE DE DATOS (SQLite) =========

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()

        # Crear tablas si no existen
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            phone TEXT UNIQUE,
            address TEXT,
            emergency_name TEXT,
            emergency_phone TEXT,
            domicilio_path TEXT,
            id_path TEXT,
            has_12m_job INTEGER,
            is_recommended INTEGER,
            can_pay_weekly INTEGER,
            accepts_terms INTEGER,
            created_at TEXT
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            loan_date TEXT,
            principal REAL,
            interest_rate REAL,
            total_to_pay REAL,
            weeks INTEGER,
            weekly_payment REAL,
            status TEXT,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER,
            payment_date TEXT,
            amount REAL,
            created_at TEXT,
            FOREIGN KEY(loan_id) REFERENCES loans(id)
        );
        """)

        # ---- MIGRACIÓN: asegurar columnas nuevas en clients ----
        cursor.execute("PRAGMA table_info(clients);")
        existing_cols = {row[1] for row in cursor.fetchall()}

        columnas_necesarias = [
            ("domicilio_path", "TEXT"),
            ("id_path", "TEXT"),
            ("has_12m_job", "INTEGER"),
            ("is_recommended", "INTEGER"),
            ("can_pay_weekly", "INTEGER"),
            ("accepts_terms", "INTEGER"),
        ]

        for col_name, col_type in columnas_necesarias:
            if col_name not in existing_cols:
                cursor.execute(
                    f"ALTER TABLE clients ADD COLUMN {col_name} {col_type};"
                )

        conn.commit()


def get_client_by_phone(phone: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM clients WHERE phone = ?", (phone,))
        return cursor.fetchone()


def upsert_client(
    full_name,
    phone,
    address,
    emergency_name,
    emergency_phone,
    domicilio_url,
    id_url,
    has_12m_job,
    is_recommended,
    can_pay_weekly,
    accepts_terms,
):
    with get_connection() as conn:
        cursor = conn.cursor()
        existing = get_client_by_phone(phone)
        if existing:
            client_id = existing[0]
            cursor.execute("""
                UPDATE clients
                SET full_name = ?, address = ?, emergency_name = ?, emergency_phone = ?,
                    domicilio_path = ?, id_path = ?, has_12m_job = ?, is_recommended = ?,
                    can_pay_weekly = ?, accepts_terms = ?
                WHERE phone = ?;
            """, (
                full_name, address, emergency_name, emergency_phone,
                domicilio_url, id_url, has_12m_job, is_recommended,
                can_pay_weekly, accepts_terms, phone
            ))
        else:
            cursor.execute("""
                INSERT INTO clients (
                    full_name, phone, address, emergency_name, emergency_phone,
                    domicilio_path, id_path, has_12m_job, is_recommended,
                    can_pay_weekly, accepts_terms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, DATE('now'));
            """, (
                full_name, phone, address, emergency_name, emergency_phone,
                domicilio_url, id_url, has_12m_job, is_recommended,
                can_pay_weekly, accepts_terms
            ))
            client_id = cursor.lastrowid

        conn.commit()
        return client_id


def create_loan(client_id, principal, loan_date):
    interest_rate = 0.5
    weeks = 12
    total_to_pay = principal * (1 + interest_rate)
    weekly_payment = total_to_pay / weeks

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO loans (
                client_id, loan_date, principal, interest_rate,
                total_to_pay, weeks, weekly_payment, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'activo');
        """, (
            client_id, loan_date.isoformat(), principal, interest_rate,
            total_to_pay, weeks, weekly_payment
        ))
        conn.commit()
        return cursor.lastrowid, weekly_payment, total_to_pay


def search_loans_by_client(text: str):
    like_pattern = f"%{text}%"
    with get_connection() as conn:
        query = """
        SELECT
            loans.id AS loan_id,
            clients.full_name,
            clients.phone,
            loans.principal,
            loans.total_to_pay,
            loans.weekly_payment,
            loans.status
        FROM loans
        JOIN clients ON loans.client_id = clients.id
        WHERE clients.phone LIKE ?
           OR clients.full_name LIKE ?
        ORDER BY loans.id DESC;
        """
        return pd.read_sql_query(query, conn, params=(like_pattern, like_pattern))


def get_loan(loan_id: int):
    with get_connection() as conn:
        query = """
        SELECT
            loans.*,
            clients.full_name,
            clients.phone,
            clients.address,
            clients.domicilio_path,
            clients.id_path
        FROM loans
        JOIN clients ON loans.client_id = clients.id
        WHERE loans.id = ?;
        """
        df = pd.read_sql_query(query, conn, params=(loan_id,))
    if df.empty:
        return None
    return df.iloc[0]


def get_payments_for_loan(loan_id: int):
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT * FROM payments WHERE loan_id = ? ORDER BY payment_date;",
            conn,
            params=(loan_id,),
        )


def insert_payment(loan_id: int, payment_date: date, amount: float):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO payments (loan_id, payment_date, amount, created_at)
            VALUES (?, ?, ?, DATE('now'));
        """, (loan_id, payment_date.isoformat(), amount))
        conn.commit()


def get_all_clients():
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM clients ORDER BY id DESC;", conn)


def get_all_loans_with_clients():
    with get_connection() as conn:
        query = """
        SELECT
            loans.id AS loan_id,
            clients.full_name,
            clients.phone,
            loans.loan_date,
            loans.principal,
            loans.total_to_pay,
            loans.weekly_payment,
            loans.status
        FROM loans
        JOIN clients ON loans.client_id = clients.id
        ORDER BY loans.id DESC;
        """
        return pd.read_sql_query(query, conn)


# ========= PÁGINAS STREAMLIT =========

def page_registrar_credito():
    st.header("📋 Registrar nuevo crédito - The Lemonade Cash")

    # --------- Inicializar estado de precalificación ---------
    if "precal_aprobada" not in st.session_state:
        st.session_state["precal_aprobada"] = False
    if "precal_principal" not in st.session_state:
        st.session_state["precal_principal"] = 0.0
    if "precal_has_12m_job" not in st.session_state:
        st.session_state["precal_has_12m_job"] = False
    if "precal_is_recommended" not in st.session_state:
        st.session_state["precal_is_recommended"] = False
    if "precal_can_pay_weekly" not in st.session_state:
        st.session_state["precal_can_pay_weekly"] = False
    if "precal_accepts_terms" not in st.session_state:
        st.session_state["precal_accepts_terms"] = False
    if "precal_loan_date" not in st.session_state:
        st.session_state["precal_loan_date"] = date.today()

    # --------- PASO 1: PRECALIFICACIÓN ---------
    st.subheader("1. Precalificación del crédito")

    with st.form("form_precal"):
        principal = st.number_input(
            "Monto del crédito solicitado",
            min_value=0.0,
            step=50.0,
            value=float(st.session_state.get("precal_principal", 0.0)),
        )

        has_12m_job = st.checkbox(
            "Tiene más de 12 meses en el trabajo actual",
            value=st.session_state.get("precal_has_12m_job", False),
        )
        is_recommended = st.checkbox(
            "Es recomendado de alguien que conozcamos",
            value=st.session_state.get("precal_is_recommended", False),
        )
        can_pay_weekly = st.checkbox(
            "Puede pagar semanalmente la cuota establecida",
            value=st.session_state.get("precal_can_pay_weekly", False),
        )
        accepts_terms = st.checkbox(
            "Está de acuerdo con el valor de su pago y condiciones del crédito",
            value=st.session_state.get("precal_accepts_terms", False),
        )

        loan_date = st.date_input(
            "Fecha del préstamo",
            value=st.session_state.get("precal_loan_date", date.today()),
        )

        submitted_precal = st.form_submit_button("Evaluar pre-calificación")

    if submitted_precal:
        if principal <= 0:
            st.error("Debes capturar un monto de crédito mayor a 0.")
            st.session_state["precal_aprobada"] = False
        elif not (has_12m_job and is_recommended and can_pay_weekly and accepts_terms):
            st.error(
                "El cliente no cumple con todos los criterios de precalificación. "
                "Revisa las respuestas del check."
            )
            st.session_state["precal_aprobada"] = False
        else:
            # Guardamos en sesión los datos de la precalificación aprobada
            st.session_state["precal_aprobada"] = True
            st.session_state["precal_principal"] = principal
            st.session_state["precal_has_12m_job"] = has_12m_job
            st.session_state["precal_is_recommended"] = is_recommended
            st.session_state["precal_can_pay_weekly"] = can_pay_weekly
            st.session_state["precal_accepts_terms"] = accepts_terms
            st.session_state["precal_loan_date"] = loan_date

            interest_rate = 0.5
            weeks = 12
            total_to_pay = principal * (1 + interest_rate)
            weekly_payment = total_to_pay / weeks

            st.success("Precalificación aprobada.")
            st.info(
                f"Monto solicitado: ${principal:,.2f}\n\n"
                f"Total a pagar (50% interés): ${total_to_pay:,.2f}\n\n"
                f"Plazo: 12 semanas\n\n"
                f"**Pago semanal estimado:** ${weekly_payment:,.2f}"
            )

    # --------- PASO 2: DATOS DEL CLIENTE Y DOCUMENTOS ---------
    if st.session_state["precal_aprobada"]:
        st.markdown("---")
        st.subheader("2. Datos del cliente y documentos")

        # Mostramos el monto aprobado en modo solo lectura
        principal_aprobado = st.session_state["precal_principal"]
        loan_date = st.session_state["precal_loan_date"]

        st.markdown(
            f"**Monto aprobado:** ${principal_aprobado:,.2f}  |  "
            f"**Fecha del préstamo:** {loan_date.strftime('%Y-%m-%d')}"
        )

        with st.form("form_datos_cliente"):
            st.markdown("### Datos del cliente")
            full_name = st.text_input("Nombre completo")
            phone = st.text_input("Teléfono (llave única)")
            address = st.text_area("Dirección")
            emergency_name = st.text_input("Nombre contacto de emergencia")
            emergency_phone = st.text_input("Teléfono contacto de emergencia")

            st.markdown("### Documentos")
            domicilio_file = st.file_uploader(
                "Comprobante de domicilio (foto)",
                type=["png", "jpg", "jpeg"],
                key="domicilio",
            )
            id_file = st.file_uploader(
                "Identificación oficial (foto)",
                type=["png", "jpg", "jpeg"],
                key="id_file",
            )

            submitted_final = st.form_submit_button("Guardar cliente y crédito")

        if submitted_final:
            if not phone:
                st.error("Debes capturar al menos el teléfono del cliente.")
                return

            # Stub: no se sube a Drive, pero mantenemos la lógica
            domicilio_url = save_uploaded_file_to_drive(
                domicilio_file, f"{phone}_domicilio"
            )
            id_url = save_uploaded_file_to_drive(
                id_file, f"{phone}_id"
            )

            # Guardar/actualizar cliente en SQLite
            client_id = upsert_client(
                full_name=full_name,
                phone=phone,
                address=address,
                emergency_name=emergency_name,
                emergency_phone=emergency_phone,
                domicilio_url=domicilio_url,
                id_url=id_url,
                has_12m_job=int(st.session_state["precal_has_12m_job"]),
                is_recommended=int(st.session_state["precal_is_recommended"]),
                can_pay_weekly=int(st.session_state["precal_can_pay_weekly"]),
                accepts_terms=int(st.session_state["precal_accepts_terms"]),
            )

            # Crear crédito en SQLite
            loan_id, weekly_payment, total_to_pay = create_loan(
                client_id=client_id,
                principal=principal_aprobado,
                loan_date=loan_date,
            )

            # Registrar también en Google Sheets
            append_loan_to_sheet(
                loan_id=loan_id,
                loan_date=loan_date,
                principal=principal_aprobado,
                total_to_pay=total_to_pay,
                weekly_payment=weekly_payment,
                full_name=full_name,
                phone=phone,
                address=address,
                emergency_name=emergency_name,
                emergency_phone=emergency_phone,
                has_12m_job=st.session_state["precal_has_12m_job"],
                is_recommended=st.session_state["precal_is_recommended"],
                can_pay_weekly=st.session_state["precal_can_pay_weekly"],
                accepts_terms=st.session_state["precal_accepts_terms"],
                domicilio_url=domicilio_url,
                id_url=id_url,
            )

            st.success(f"Crédito #{loan_id} registrado correctamente.")
            st.info(
                f"Monto prestado: ${principal_aprobado:,.2f}\n\n"
                f"Total a pagar (50% interés): ${total_to_pay:,.2f}\n\n"
                f"Plazo: 12 semanas\n\n"
                f"**Pago semanal:** ${weekly_payment:,.2f}"
            )

            # Limpiar estado de precalificación para el siguiente cliente
            for key in [
                "precal_aprobada",
                "precal_principal",
                "precal_has_12m_job",
                "precal_is_recommended",
                "precal_can_pay_weekly",
                "precal_accepts_terms",
                "precal_loan_date",
            ]:
                if key in st.session_state:
                    del st.session_state[key]


def page_registrar_pago():
    st.header("✅ Registrar pago semanal - The Lemonade Cash")

    search_text = st.text_input("Buscar cliente por nombre o teléfono:")
    if not search_text:
        st.info("Escribe al menos parte del nombre o teléfono para buscar.")
        return

    loans_df = search_loans_by_client(search_text)
    if loans_df.empty:
        st.warning("No se encontraron créditos para ese criterio.")
        return

    st.subheader("Resultados")
    st.dataframe(loans_df, use_container_width=True, hide_index=True)

    loan_ids = loans_df["loan_id"].tolist()
    selected_loan_id = st.selectbox(
        "Selecciona el crédito",
        loan_ids,
        format_func=lambda x: f"Crédito #{x}",
    )

    loan = get_loan(selected_loan_id)
    if loan is None:
        st.error("No se pudo cargar el crédito.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Cliente**")
        st.write(f"Nombre: {loan['full_name']}")
        st.write(f"Teléfono: {loan['phone']}")
        st.write(f"Dirección: {loan['address']}")
        if loan["domicilio_path"]:
            st.write(f"[Comprobante de domicilio]({loan['domicilio_path']})")
        if loan["id_path"]:
            st.write(f"[Identificación]({loan['id_path']})")

    with col2:
        st.markdown("**Crédito**")
        st.write(f"Fecha del préstamo: {loan['loan_date']}")
        st.write(f"Monto: ${loan['principal']:,.2f}")
        st.write(f"Total a pagar: ${loan['total_to_pay']:,.2f}")
        st.write(f"Pago semanal: ${loan['weekly_payment']:,.2f}")
        st.write(f"Estado: {loan['status']}")

    payments_df = get_payments_for_loan(selected_loan_id)
    total_pagado = payments_df["amount"].sum() if not payments_df.empty else 0.0
    restante = loan["total_to_pay"] - total_pagado

    st.subheader("Resumen de pagos")
    st.write(f"Pagos registrados: {len(payments_df)}")
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
        insert_payment(selected_loan_id, payment_date, amount)
        st.success(f"Pago de ${amount:,.2f} registrado.")
        st.experimental_rerun()


def page_ver_base():
    st.header("📚 Base de datos - The Lemonade Cash")

    st.subheader("Clientes")
    clients_df = get_all_clients()
    if clients_df.empty:
        st.info("No hay clientes registrados.")
    else:
        st.dataframe(clients_df, use_container_width=True)

    st.subheader("Créditos")
    loans_df = get_all_loans_with_clients()
    if loans_df.empty:
        st.info("No hay créditos registrados.")
    else:
        st.dataframe(loans_df, use_container_width=True)


# ========= MAIN =========

def main():
    st.set_page_config(page_title="The Lemonade Cash", page_icon="🍋", layout="wide")
    init_db()

    st.title("🍋 The Lemonade Cash")
    st.write("Control de préstamos semanales a 12 semanas con 50% de interés.")

    menu = st.sidebar.selectbox(
        "Navegación",
        ["Registrar nuevo crédito", "Registrar pago semanal", "Ver base de datos"],
    )

    if menu == "Registrar nuevo crédito":
        page_registrar_credito()
    elif menu == "Registrar pago semanal":
        page_registrar_pago()
    elif menu == "Ver base de datos":
        page_ver_base()


if __name__ == "__main__":
    main()
