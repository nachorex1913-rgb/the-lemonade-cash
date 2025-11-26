import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ================== CONFIGURACIÓN GENERAL ==================

DB_NAME = "lemonade_cash.db"

# Solo Sheets (Drive queda manual)
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ID de tu Google Sheet (YA FUNCIONA)
SPREADSHEET_ID_FIXED = "1tk1rm8h4ETGnmM4DwTDKGmaVnoGx-Q6MOmEcBUr5pTc"

# URL base de búsqueda en Google Drive por texto
DRIVE_SEARCH_BASE_URL = "https://drive.google.com/drive/u/0/search?q="


# ================== GOOGLE SHEETS ==================

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
    docs_url,
    sequence,
    first_due_date,
):
    """
    Agrega una fila a Google Sheets con datos del crédito.
    Usa el ID fijo de tu hoja de cálculo.
    """

    spreadsheet_id = SPREADSHEET_ID_FIXED
    service = get_sheets_service()

    def yes_no(v):
        return "SI" if v else "NO"

    values = [[
        str(date.today()),               # Fecha de registro en el sistema
        loan_id,                         # ID interno del crédito
        sequence,                        # Número de crédito para ese cliente (1, 2, 3...)
        loan_date.isoformat(),           # Fecha del préstamo
        first_due_date.isoformat(),      # Fecha del primer pago (sábado según regla)
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
        docs_url or "",
    ]]

    body = {"values": values}

    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range="Prestamos!A1",  # pestaña "Prestamos"
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()


# ================== CÁLCULO DE FECHAS DE PAGO ==================

def get_first_due_date(loan_date: date) -> date:
    """
    Regla:
    - Siempre se paga en sábado.
    - Si el préstamo se hace con al menos 3 días de anticipación al sábado (Dom, Lun, Mar, Mié),
      el primer pago es ese mismo sábado.
    - Si está "muy cerca" (Jue, Vie, Sáb), el primer pago es el sábado de arriba (una semana después).
    """
    weekday = loan_date.weekday()  # lunes=0 ... domingo=6
    # Próximo sábado de ESTA semana
    days_to_this_saturday = (5 - weekday) % 7

    if days_to_this_saturday >= 3:
        # Hay margen suficiente → paga este sábado
        first = loan_date + timedelta(days=days_to_this_saturday)
    else:
        # Muy cerca → paga el sábado de arriba
        first = loan_date + timedelta(days=days_to_this_saturday + 7)

    return first


# ================== BASE DE DATOS (SQLite) ==================

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()

        # Tabla de clientes
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
            created_at TEXT,
            rating INTEGER
        );
        """)

        # Tabla de créditos
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
            first_due_date TEXT,
            sequence INTEGER,
            FOREIGN KEY(client_id) REFERENCES clients(id)
        );
        """)

        # Tabla de pagos
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

        # --------- Migraciones: asegurar columnas nuevas ---------
        cursor.execute("PRAGMA table_info(clients);")
        existing_client_cols = {row[1] for row in cursor.fetchall()}
        if "rating" not in existing_client_cols:
            cursor.execute("ALTER TABLE clients ADD COLUMN rating INTEGER;")

        cursor.execute("PRAGMA table_info(loans);")
        existing_loan_cols = {row[1] for row in cursor.fetchall()}
        if "first_due_date" not in existing_loan_cols:
            cursor.execute("ALTER TABLE loans ADD COLUMN first_due_date TEXT;")
        if "sequence" not in existing_loan_cols:
            cursor.execute("ALTER TABLE loans ADD COLUMN sequence INTEGER;")

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
    docs_url,
    has_12m_job,
    is_recommended,
    can_pay_weekly,
    accepts_terms,
):
    """
    Guardamos la URL de documentos (búsqueda en Drive) en domicilio_path e id_path,
    y dejamos rating separado (para editarlo después).
    """
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
                docs_url, docs_url, has_12m_job, is_recommended,
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
                docs_url, docs_url, has_12m_job, is_recommended,
                can_pay_weekly, accepts_terms
            ))
            client_id = cursor.lastrowid

        conn.commit()
        return client_id


def get_client_by_id(client_id: int):
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT * FROM clients WHERE id = ?;",
            conn,
            params=(client_id,),
        ).iloc[0]


def count_loans_for_client(client_id: int) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM loans WHERE client_id = ?", (client_id,))
        (count,) = cursor.fetchone()
        return count


def create_loan(client_id, principal, loan_date: date):
    """
    Crea un crédito:
    - 50% de interés
    - 12 semanas
    - Calcula fecha del primer pago (sábado)
    - Asigna número de crédito (1°, 2°, 3°, ...) para ese cliente
    """
    interest_rate = 0.5
    weeks = 12
    total_to_pay = principal * (1 + interest_rate)
    weekly_payment = total_to_pay / weeks
    first_due = get_first_due_date(loan_date)

    # Número de crédito para ese cliente
    prev_loans = count_loans_for_client(client_id)
    sequence = prev_loans + 1

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO loans (
                client_id, loan_date, principal, interest_rate,
                total_to_pay, weeks, weekly_payment, status,
                first_due_date, sequence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'activo', ?, ?);
        """, (
            client_id, loan_date.isoformat(), principal, interest_rate,
            total_to_pay, weeks, weekly_payment, first_due.isoformat(), sequence
        ))
        conn.commit()
        return cursor.lastrowid, weekly_payment, total_to_pay, sequence, first_due


def search_loans_by_client(text: str):
    like_pattern = f"%{text}%"
    with get_connection() as conn:
        query = """
        SELECT
            loans.id AS loan_id,
            loans.sequence,
            clients.full_name,
            clients.phone,
            loans.loan_date,
            loans.first_due_date,
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
            clients.id_path,
            clients.rating
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


def update_loan_status_if_paid(loan_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT total_to_pay FROM loans WHERE id = ?", (loan_id,))
        row = cursor.fetchone()
        if not row:
            return
        total_to_pay = row[0]

        cursor.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE loan_id = ?",
            (loan_id,),
        )
        (paid_sum,) = cursor.fetchone()

        if paid_sum >= total_to_pay - 0.01:
            cursor.execute(
                "UPDATE loans SET status = 'cerrado' WHERE id = ?",
                (loan_id,),
            )

        conn.commit()


def insert_payment(loan_id: int, payment_date: date, amount: float):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO payments (loan_id, payment_date, amount, created_at)
            VALUES (?, ?, ?, DATE('now'));
        """, (loan_id, payment_date.isoformat(), amount))
        conn.commit()
    update_loan_status_if_paid(loan_id)


def get_all_clients():
    with get_connection() as conn:
        return pd.read_sql_query("SELECT * FROM clients ORDER BY id DESC;", conn)


def get_all_loans_with_clients(status_filter=None):
    with get_connection() as conn:
        base_query = """
        SELECT
            loans.id AS loan_id,
            loans.sequence,
            clients.full_name,
            clients.phone,
            loans.loan_date,
            loans.first_due_date,
            loans.principal,
            loans.total_to_pay,
            loans.weekly_payment,
            loans.status
        FROM loans
        JOIN clients ON loans.client_id = clients.id
        """
        if status_filter is None:
            query = base_query + " ORDER BY loans.id DESC;"
            return pd.read_sql_query(query, conn)
        else:
            query = base_query + " WHERE loans.status = ? ORDER BY loans.id DESC;"
            return pd.read_sql_query(query, conn, params=(status_filter,))


def update_client_rating(client_id: int, rating: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE clients SET rating = ? WHERE id = ?;",
            (rating, client_id),
        )
        conn.commit()


# ================== PÁGINA: WIZARD DE REGISTRO ==================

def page_wizard_registro():
    st.header("🧩 Registro de crédito - Wizard por pasos")

    # Estado del wizard
    if "wizard_step" not in st.session_state:
        st.session_state["wizard_step"] = 1
    if "wizard_data" not in st.session_state:
        st.session_state["wizard_data"] = {}

    step = st.session_state["wizard_step"]
    wizard_data = st.session_state["wizard_data"]

    # Barra de avance
    st.progress(step / 3)
    st.caption(f"Paso {step} de 3")

    # ----- PASO 1: Precalificación -----
    if step == 1:
        st.subheader("Paso 1: Precalificación")

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

            submitted_precal = st.form_submit_button("Evaluar pre-calificación")

        if submitted_precal:
            if principal <= 0:
                st.error("Debes capturar un monto de crédito mayor a 0.")
            elif not (has_12m_job and is_recommended and can_pay_weekly and accepts_terms):
                st.error(
                    "El cliente no cumple con todos los criterios de precalificación. "
                    "Revisa las respuestas del check."
                )
            else:
                # Guardamos en el wizard
                wizard_data.update({
                    "principal": principal,
                    "has_12m_job": has_12m_job,
                    "is_recommended": is_recommended,
                    "can_pay_weekly": can_pay_weekly,
                    "accepts_terms": accepts_terms,
                    "loan_date": loan_date,
                })
                st.session_state["wizard_data"] = wizard_data

                interest_rate = 0.5
                weeks = 12
                total_to_pay = principal * (1 + interest_rate)
                weekly_payment = total_to_pay / weeks
                first_due = get_first_due_date(loan_date)

                st.success("Precalificación aprobada.")
                st.info(
                    f"Monto solicitado: ${principal:,.2f}\n\n"
                    f"Total a pagar (50% interés): ${total_to_pay:,.2f}\n\n"
                    f"Plazo: 12 semanas\n\n"
                    f"Pago semanal estimado: ${weekly_payment:,.2f}\n\n"
                    f"Primer pago programado para el sábado: {first_due.strftime('%Y-%m-%d')}"
                )

                # Avanzar al paso 2
                st.session_state["wizard_step"] = 2

    # ----- PASO 2: Registrar cliente -----
    elif step == 2:
        st.subheader("Paso 2: Datos del cliente")

        if "principal" not in wizard_data:
            st.warning("Primero completa la precalificación (Paso 1).")
            if st.button("Volver al Paso 1"):
                st.session_state["wizard_step"] = 1
            return

        with st.form("form_datos_cliente"):
            full_name = st.text_input("Nombre completo", value=wizard_data.get("full_name", ""))
            phone = st.text_input("Teléfono (llave única)", value=wizard_data.get("phone", ""))
            address = st.text_area("Dirección", value=wizard_data.get("address", ""))
            emergency_name = st.text_input(
                "Nombre contacto de emergencia", value=wizard_data.get("emergency_name", "")
            )
            emergency_phone = st.text_input(
                "Teléfono contacto de emergencia", value=wizard_data.get("emergency_phone", "")
            )

            col_a, col_b = st.columns(2)
            with col_a:
                btn_volver = st.form_submit_button("⬅️ Volver al Paso 1")
            with col_b:
                btn_siguiente = st.form_submit_button("Continuar al Paso 3 ➡️")

        if btn_volver:
            st.session_state["wizard_step"] = 1

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

    # ----- PASO 3: Subir archivos (manual en Drive) y guardar -----
    elif step == 3:
        st.subheader("Paso 3: Subida de archivos y confirmación")

        if "phone" not in wizard_data:
            st.warning("Primero completa los datos del cliente (Paso 2).")
            if st.button("Volver al Paso 2"):
                st.session_state["wizard_step"] = 2
            return

        phone = wizard_data["phone"]
        docs_url = f"{DRIVE_SEARCH_BASE_URL}{phone}"

        st.markdown("### Instrucciones para documentos")
        st.markdown(
            f"""
            1. Sube los documentos (INE, comprobante de domicilio, etc.) **directamente en tu Google Drive**.
            2. Usa SIEMPRE el **teléfono del cliente** (`{phone}`) en el nombre de la carpeta o archivos.
            3. Puedes usar este enlace para buscar rápidamente los documentos de este cliente en Drive:

            👉 [**Buscar documentos en Drive para {phone}**]({docs_url})
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

        if btn_guardar:
            if not docs_ok:
                st.error("Marca la casilla de confirmación de documentos para continuar.")
                return

            # Recuperamos datos del wizard
            principal = float(wizard_data["principal"])
            loan_date = wizard_data["loan_date"]
            has_12m_job = int(wizard_data["has_12m_job"])
            is_recommended = int(wizard_data["is_recommended"])
            can_pay_weekly = int(wizard_data["can_pay_weekly"])
            accepts_terms = int(wizard_data["accepts_terms"])

            full_name = wizard_data["full_name"]
            phone = wizard_data["phone"]
            address = wizard_data["address"]
            emergency_name = wizard_data["emergency_name"]
            emergency_phone = wizard_data["emergency_phone"]

            # Guardar / actualizar cliente
            client_id = upsert_client(
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

            # Crear crédito
            loan_id, weekly_payment, total_to_pay, sequence, first_due = create_loan(
                client_id=client_id,
                principal=principal,
                loan_date=loan_date,
            )

            # Registrar en Google Sheets
            append_loan_to_sheet(
                loan_id=loan_id,
                loan_date=loan_date,
                principal=principal,
                total_to_pay=total_to_pay,
                weekly_payment=weekly_payment,
                full_name=full_name,
                phone=phone,
                address=address,
                emergency_name=emergency_name,
                emergency_phone=emergency_phone,
                has_12m_job=bool(has_12m_job),
                is_recommended=bool(is_recommended),
                can_pay_weekly=bool(can_pay_weekly),
                accepts_terms=bool(accepts_terms),
                docs_url=docs_url,
                sequence=sequence,
                first_due_date=first_due,
            )

            st.success(f"Crédito #{loan_id} registrado correctamente.")
            st.info(
                f"Crédito #{sequence} para este cliente\n\n"
                f"Monto prestado: ${principal:,.2f}\n\n"
                f"Total a pagar (50% interés): ${total_to_pay:,.2f}\n\n"
                f"Plazo: 12 semanas\n\n"
                f"Pago semanal: ${weekly_payment:,.2f}\n\n"
                f"Primer pago programado para el sábado: {first_due.strftime('%Y-%m-%d')}"
            )

            st.markdown(
                f"[Ver / buscar documentos en Drive para {phone}]({docs_url})"
            )

            # Resetear wizard para el siguiente cliente
            st.session_state["wizard_step"] = 1
            st.session_state["wizard_data"] = {}


# ================== PÁGINA: CLIENTES (con rating) ==================

def page_clientes():
    st.header("👤 Base de clientes - The Lemonade Cash")

    clients_df = get_all_clients()
    if clients_df.empty:
        st.info("No hay clientes registrados.")
        return

    st.subheader("Listado de clientes")
    cols_to_show = ["id", "full_name", "phone", "address"]
    if "rating" in clients_df.columns:
        cols_to_show.append("rating")

    st.dataframe(
        clients_df[cols_to_show],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")
    st.subheader("Editar calificación (estrellas)")

    options = [
        f"{row.id} - {row.full_name} ({row.phone})"
        for _, row in clients_df.iterrows()
    ]
    selected = st.selectbox("Selecciona un cliente", options)
    if not selected:
        return

    client_id = int(selected.split(" - ")[0])
    client_row = clients_df[clients_df["id"] == client_id].iloc[0]

    st.write(f"**Cliente:** {client_row['full_name']}  |  Tel: {client_row['phone']}")

    current_rating = client_row["rating"] if pd.notna(client_row["rating"]) else 3
    new_rating = st.slider(
        "Calificación del cliente (1 a 5 estrellas)",
        min_value=1,
        max_value=5,
        value=int(current_rating),
    )

    if st.button("Guardar calificación"):
        update_client_rating(client_id, new_rating)
        st.success("Calificación actualizada. Recarga la página para ver los cambios.")


# ================== PÁGINA: CRÉDITOS ACTIVOS ==================

def page_creditos_activos():
    st.header("💳 Créditos activos")

    loans_df = get_all_loans_with_clients(status_filter="activo")
    if loans_df.empty:
        st.info("No hay créditos activos.")
        return

    st.dataframe(
        loans_df,
        use_container_width=True,
        hide_index=True,
    )


# ================== PÁGINA: REGISTRAR PAGO ==================

def page_registrar_pago():
    st.header("✅ Registrar pago semanal - The Lemonade Cash")

    # 🔑 key distinto para este text_input
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
            st.write(
                f"[Buscar documentos en Drive para este cliente]({loan['domicilio_path']})"
            )
        if "rating" in loan.index and pd.notna(loan["rating"]):
            st.write(f"Calificación: {int(loan['rating'])} ⭐")

    with col2:
        st.markdown("**Crédito**")
        st.write(f"Número de crédito para este cliente: {loan.get('sequence', 'N/A')}")
        st.write(f"Fecha del préstamo: {loan['loan_date']}")
        st.write(f"Primer pago (sábado): {loan.get('first_due_date', '')}")
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


# ================== PÁGINA: HISTORIAL (CERRADOS) ==================

def page_historial():
    st.header("📜 Historial de créditos (cerrados)")

    loans_df = get_all_loans_with_clients(status_filter="cerrado")
    if loans_df.empty:
        st.info("No hay créditos cerrados todavía.")
        return

    st.dataframe(
        loans_df,
        use_container_width=True,
        hide_index=True,
    )


# ================== PÁGINA: CALENDARIO DE PAGOS ==================

def page_calendario():
    st.header("📆 Calendario de pagos (por crédito)")

    # 🔑 key distinto para este text_input
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

    st.subheader("Créditos encontrados")
    st.dataframe(loans_df, use_container_width=True, hide_index=True)

    loan_ids = loans_df["loan_id"].tolist()
    selected_loan_id = st.selectbox(
        "Selecciona el crédito para ver su calendario",
        loan_ids,
        format_func=lambda x: f"Crédito #{x}",
    )

    loan = get_loan(selected_loan_id)
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

    # Construimos calendario de 12 semanas
    weeks = int(loan["weeks"])
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
    st.subheader("Calendario de pagos programados")
    st.dataframe(schedule_df, use_container_width=True, hide_index=True)


# ================== MAIN ==================

def main():
    st.set_page_config(page_title="The Lemonade Cash", page_icon="🍋", layout="wide")
    init_db()

    st.title("🍋 The Lemonade Cash")
    st.write("Control de préstamos semanales a 12 semanas con 50% de interés.")

    tabs = st.tabs([
        "Registro (wizard)",
        "Clientes",
        "Créditos activos",
        "Registrar pago",
        "Historial",
        "Calendario de pagos",
    ])

    with tabs[0]:
        page_wizard_registro()
    with tabs[1]:
        page_clientes()
    with tabs[2]:
        page_creditos_activos()
    with tabs[3]:
        page_registrar_pago()
    with tabs[4]:
        page_historial()
    with tabs[5]:
        page_calendario()


if __name__ == "__main__":
    main()
