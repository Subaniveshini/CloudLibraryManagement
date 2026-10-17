from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3

app = Flask(__name__)
app.secret_key = "library-project-secret-key"

DATABASE = "library.db"


# Connect to the database
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Create the database tables
def initialize_database():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            category TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity >= 0)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            issue_date TEXT NOT NULL DEFAULT CURRENT_DATE,
            return_date TEXT,
            status TEXT NOT NULL DEFAULT 'Issued'
                CHECK(status IN ('Issued', 'Returned')),
            FOREIGN KEY(book_id) REFERENCES books(id),
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
    """)

    conn.commit()
    conn.close()


# Dashboard
@app.route("/")
def home():
    conn = get_db_connection()

    total_titles = conn.execute(
        "SELECT COUNT(*) FROM books"
    ).fetchone()[0]

    total_copies = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM books"
    ).fetchone()[0]

    issued_books = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE status = 'Issued'"
    ).fetchone()[0]

    student_count = conn.execute(
        "SELECT COUNT(*) FROM students"
    ).fetchone()[0]

    conn.close()

    return render_template(
        "index.html",
        total_titles=total_titles,
        total_copies=total_copies,
        issued_books=issued_books,
        student_count=student_count
    )


# View and search books
@app.route("/books")
def books():
    search = request.args.get("search", "").strip()

    conn = get_db_connection()

    book_list = conn.execute("""
        SELECT
            b.*,
            b.quantity - (
                SELECT COUNT(*)
                FROM issues i
                WHERE i.book_id = b.id AND i.status = 'Issued'
            ) AS available
        FROM books b
        WHERE b.title LIKE ?
           OR b.author LIKE ?
           OR b.category LIKE ?
        ORDER BY b.id DESC
    """, (f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()

    conn.close()

    return render_template(
        "books.html",
        books=book_list,
        search=search
    )


# Add a book
@app.route("/add", methods=["GET", "POST"])
def add_book():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        category = request.form.get("category", "").strip()

        try:
            quantity = int(request.form.get("quantity", "0"))
        except ValueError:
            quantity = 0

        if not title or not author or not category or quantity < 1:
            return "Please enter valid book details.", 400

        conn = get_db_connection()

        conn.execute("""
            INSERT INTO books (title, author, category, quantity)
            VALUES (?, ?, ?, ?)
        """, (title, author, category, quantity))

        conn.commit()
        conn.close()

        flash("Book added successfully!")
        return redirect(url_for("books"))

    return render_template("add_book.html")


# Register a student
@app.route("/students", methods=["GET", "POST"])
def students():
    conn = get_db_connection()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()

        if not name or not email or "@" not in email:
            conn.close()
            flash("Please enter a valid name and email.")
            return redirect(url_for("students"))

        try:
            conn.execute(
                "INSERT INTO students (name, email) VALUES (?, ?)",
                (name, email)
            )
            conn.commit()
            flash("Student registered successfully!")
        except sqlite3.IntegrityError:
            flash("This email is already registered.")

        conn.close()
        return redirect(url_for("students"))

    student_list = conn.execute(
        "SELECT * FROM students ORDER BY name"
    ).fetchall()

    conn.close()

    return render_template("students.html", students=student_list)


# Issue a book
@app.route("/issue", methods=["GET", "POST"])
def issue_book():
    conn = get_db_connection()

    if request.method == "POST":
        try:
            book_id = int(request.form.get("book_id", "0"))
            student_id = int(request.form.get("student_id", "0"))
        except ValueError:
            conn.close()
            flash("Please select a valid book and student.")
            return redirect(url_for("issue_book"))

        book = conn.execute(
            "SELECT * FROM books WHERE id = ?", (book_id,)
        ).fetchone()

        student = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()

        if not book or not student:
            conn.close()
            flash("Selected book or student does not exist.")
            return redirect(url_for("issue_book"))

        issued_count = conn.execute(
            """
            SELECT COUNT(*) FROM issues
            WHERE book_id = ? AND status = 'Issued'
            """,
            (book_id,)
        ).fetchone()[0]

        if issued_count >= book["quantity"]:
            conn.close()
            flash("No copies of this book are currently available.")
            return redirect(url_for("issue_book"))

        conn.execute(
            """
            INSERT INTO issues (book_id, student_id)
            VALUES (?, ?)
            """,
            (book_id, student_id)
        )

        conn.commit()
        conn.close()

        flash("Book issued successfully!")
        return redirect(url_for("records"))

    book_list = conn.execute(
        "SELECT * FROM books ORDER BY title"
    ).fetchall()

    student_list = conn.execute(
        "SELECT * FROM students ORDER BY name"
    ).fetchall()

    conn.close()

    return render_template(
        "issue.html",
        books=book_list,
        students=student_list
    )


# View borrowing records and return books
@app.route("/records", methods=["GET", "POST"])
def records():
    conn = get_db_connection()

    if request.method == "POST":
        try:
            issue_id = int(request.form.get("issue_id", "0"))
        except ValueError:
            conn.close()
            flash("Invalid borrowing record.")
            return redirect(url_for("records"))

        cursor = conn.execute(
            """
            UPDATE issues
            SET status = 'Returned', return_date = CURRENT_DATE
            WHERE id = ? AND status = 'Issued'
            """,
            (issue_id,)
        )

        conn.commit()
        conn.close()

        if cursor.rowcount:
            flash("Book returned successfully!")
        else:
            flash("Record not found or book already returned.")

        return redirect(url_for("records"))

    issue_list = conn.execute("""
        SELECT
            issues.id,
            books.title,
            students.name,
            issues.issue_date,
            issues.return_date,
            issues.status
        FROM issues
        JOIN books ON issues.book_id = books.id
        JOIN students ON issues.student_id = students.id
        ORDER BY issues.id DESC
    """).fetchall()

    conn.close()

    return render_template("records.html", records=issue_list)


# Delete a book if it has no borrowing history
@app.route("/delete/<int:book_id>", methods=["POST"])
def delete_book(book_id):
    conn = get_db_connection()

    history = conn.execute(
        "SELECT COUNT(*) FROM issues WHERE book_id = ?",
        (book_id,)
    ).fetchone()[0]

    if history:
        conn.close()
        flash("This book has borrowing records and cannot be deleted.")
        return redirect(url_for("books"))

    conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()

    flash("Book deleted successfully!")
    return redirect(url_for("books"))


if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)