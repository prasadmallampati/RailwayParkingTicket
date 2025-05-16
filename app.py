from flask import Flask, render_template, request, redirect, url_for, session, Response, make_response
from datetime import datetime
import sqlite3
import csv
import io

app = Flask(__name__)
app.secret_key = 'your_secret_key'

def init_db():
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_number TEXT NOT NULL,
        vehicle_type TEXT NOT NULL,
        entry_time TEXT NOT NULL,
        exit_time TEXT,
        charge REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()

init_db()

RATES = {
    '2-wheeler': 10,
    '4-wheeler': 20
}

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'username' not in session:
        return redirect(url_for('login'))

    query = "SELECT * FROM tickets WHERE exit_time IS NULL"
    params = []

    if request.method == 'POST':
        vehicle_number = request.form.get('vehicle_number')
        vehicle_type = request.form.get('vehicle_type')

        if vehicle_number:
            query += " AND vehicle_number LIKE ?"
            params.append(f"%{vehicle_number}%")
        if vehicle_type and vehicle_type != 'All':
            query += " AND vehicle_type = ?"
            params.append(vehicle_type)

    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute(query, params)
    tickets = c.fetchall()
    conn.close()

    response = make_response(render_template('index.html', tickets=tickets))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/new_ticket', methods=['POST'])
def new_ticket():
    if 'username' not in session:
        return redirect(url_for('login'))

    vehicle_number = request.form['vehicle_number'].upper()
    vehicle_type = request.form['vehicle_type']
    entry_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute("SELECT * FROM tickets WHERE vehicle_number = ? AND exit_time IS NULL", (vehicle_number,))
    existing = c.fetchone()
    if existing:
        conn.close()
        return render_template('index.html', tickets=[], error=f"Vehicle {vehicle_number} already has an active ticket.")

    c.execute("INSERT INTO tickets (vehicle_number, vehicle_type, entry_time) VALUES (?, ?, ?)",
              (vehicle_number, vehicle_type, entry_time))
    ticket_id = c.lastrowid
    conn.commit()
    conn.close()
    return redirect(url_for('print_ticket', ticket_id=ticket_id))

@app.route('/exit_ticket/<int:ticket_id>', methods=['GET', 'POST'])
def exit_ticket(ticket_id):
    if 'username' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('parking.db')
    c = conn.cursor()

    if request.method == 'POST':
        charge = float(request.form['charge'])
        exit_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("UPDATE tickets SET exit_time=?, charge=? WHERE id=?", (exit_time, charge, ticket_id))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    c.execute("SELECT entry_time, vehicle_type FROM tickets WHERE id=?", (ticket_id,))
    entry_time_str, vehicle_type = c.fetchone()
    entry_time = datetime.strptime(entry_time_str, '%Y-%m-%d %H:%M:%S')
    duration = (datetime.now() - entry_time).total_seconds() / 3600
    charge = RATES[vehicle_type] * max(1, int(duration))
    conn.close()
    return render_template('confirm_exit.html', ticket_id=ticket_id, vehicle_type=vehicle_type, entry_time=entry_time_str, charge=charge)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('parking.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()
        if user:
            session['username'] = username
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('parking.db')
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            conn.commit()
        except sqlite3.IntegrityError:
            return render_template('register.html', error='Username already exists')
        finally:
            conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'username' not in session:
        return redirect(url_for('login'))

    query = "SELECT * FROM tickets WHERE exit_time IS NOT NULL"
    params = []

    if request.method == 'POST':
        vehicle_number = request.form.get('vehicle_number')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')

        if vehicle_number:
            query += " AND vehicle_number LIKE ?"
            params.append(f"%{vehicle_number}%")
        if start_date:
            query += " AND DATE(entry_time) >= ?"
            params.append(start_date)
        if end_date:
            query += " AND DATE(entry_time) <= ?"
            params.append(end_date)

    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute(query, params)
    tickets = c.fetchall()
    conn.close()
    return render_template('report.html', tickets=tickets)

@app.route('/export_csv')
def export_csv():
    if 'username' not in session:
        return redirect(url_for('login'))
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute("SELECT * FROM tickets")
    tickets = c.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Vehicle Number', 'Vehicle Type', 'Entry Time', 'Exit Time', 'Charge'])
    writer.writerows(tickets)
    output.seek(0)
    conn.close()
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': 'attachment;filename=tickets_report.csv'})

@app.route('/print_ticket/<int:ticket_id>')
def print_ticket(ticket_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,))
    ticket = c.fetchone()
    conn.close()
    return render_template('print_ticket.html', ticket=ticket)

@app.route('/summary')
def summary():
    if 'username' not in session:
        return redirect(url_for('login'))
    conn = sqlite3.connect('parking.db')
    c = conn.cursor()
    c.execute("SELECT vehicle_type, COUNT(*) FROM tickets WHERE exit_time IS NULL GROUP BY vehicle_type")
    data = c.fetchall()
    c.execute("SELECT COUNT(*) FROM tickets WHERE exit_time IS NULL")
    total = c.fetchone()[0]
    conn.close()
    return render_template('summary.html', data=data, total=total)

if __name__ == '__main__':
    app.run(debug=True)
