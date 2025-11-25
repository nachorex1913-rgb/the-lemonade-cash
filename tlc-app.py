import streamlit as st
import sqlite3
import pandas as pd
from datetime import date

DB_NAME = "lemonade_cash.db"

# ========= BASE DE DATOS =========

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT,
            phone TEXT UNIQUE,
            address TEXT,
            emergency_name TEXT,
            emergency_phone TEXT,
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
    has_12m_job,
    is_recommended,
    can_pay_weekly,
    accepts_terms
):
    with get_connection() as conn:
        cursor = conn.cursor()
        existing = get_client_by_phone(phone)
        if existing:
            client_id = existing[0]
            cursor.execute("""
                UPDATE clients
                SET full_name = ?, address = ?, emergency_name = ?, emergency_phone = ?,
                    has_12m_job = ?, is_recommended = ?, can_pay_weekly = ?, accepts_terms = ?
                WHERE phone = ?;
            """, (
                full_name, address, emergency_name, emergency_phone,
                has_12m_job, is_recommended, can_pay_weekly, accepts_terms, phone
            ))
        else:
            cursor.execute("""
                INSERT INTO clients (
                    full_name, phone, address, emergency_name, emergency_phone,
                    has_12m_job, is_recommended, can_pay_weekly, accepts_terms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, DATE('now'));
            """, (
                full_name, phone, address, emergency_name, emergency_phone,
                has_12m_job, is_recommended, can_pay_weekly, accepts_terms
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
            clients.address
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
            params=(loan_id,)
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

    with st.form("form_credito"):
        st.subheader("Datos del cliente")
        full_name = st.text_input("Nombre completo")
        phone = st.text_input("Teléfono (llave única)")
        address = st.text_area("Dirección")
        emergency_name = st.text_input("Nombre contacto de emergencia")
        emergency_phone = st.text_input("Teléfono contacto de emergencia")

        st.subheader("Validación del cliente")
        has_12m_job = st.checkbox("Tiene más de 12 meses en el trabajo actual")
        is_recommended = st.checkbox("Es recomendado de alguien que conozcamos")
        can_pay_weekly = st.checkbox("Puede pagar semanalmente la cuota establecida")
        accepts_terms = st.checkbox("Está de acuerdo con el valor de su pago y condiciones del crédito")

        st.subheader("Datos del crédito")
        loan_date = st.date_input("Fecha del préstamo", value=date.today())
        principal = st.number_input("Monto del crédito", min_value=0.0, step=50.0)

        submitted = st.form_submit_button("Guardar cliente y crédito")

    if submitted:
        if not phone or principal <= 0:
            st.error("Debes capturar al menos el teléfono y un monto de crédito mayor a 0.")
            return

        client_id = upsert_client(
            full_name=full_name,
            phone=phone,
            address=address,
            emergency_name=emergency_name,
            emergency_phone=emergency_phone,
            has_12m_job=int(has_12m_job),
            is_recommended=int(is_recommended),
            can_pay_weekly=int(can_pay_weekly),
            accepts_terms=int(accepts_terms),
        )

        loan_id, weekly_payment, total_to_pay = create_loan(
            client_id=client_id,
            principal=principal,
            loan_date=loan_date
        )

        st.success(f"Crédito #{loan_id} registrado correctamente.")
        st.info(
            f"Monto prestado: ${principal:,.2f}\n\n"
            f"Total a pagar (50% interés): ${total_to_pay:,.2f}\n\n"
            f"Plazo: 12 semanas\n\n"
            f"**Pago semanal:** ${weekly_payment:,.2f}"
        )

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
        format_func=lambda x: f"Crédito #{x}"
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
            hide_index=True
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
        ["Registrar nuevo crédito", "Registrar pago semanal", "Ver base de datos"]
    )

    if menu == "Registrar nuevo crédito":
        page_registrar_credito()
    elif menu == "Registrar pago semanal":
        page_registrar_pago()
    elif menu == "Ver base de datos":
        page_ver_base()

if __name__ == "__main__":
    main()

