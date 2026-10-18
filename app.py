import os
from flask import Flask, render_template, request, redirect, url_for, flash
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "temporary-local-development-key")

DATABASE_URL = os.environ.get("DATABASE_URL")


# Connect to Supabase PostgreSQL
def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Please check your .env file."
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10
    )


# Dashboard
@app.route("/")
def home():
    with get_db_connection() as conn:
        total_titles = conn.execute(
            "SELECT COUNT(*) AS count FROM books"
        ).fetchone()["count"]

        total_copies = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total FROM books"
        ).fetchone()["total"]

        issued_books = conn.execute(
            "SELECT COUNT(*) AS count FROM issues WHERE status = 'Issued'"
        ).fetchone()["count"]

        student_count = conn.execute(
            "SELECT COUNT(*) AS count FROM students"
        ).fetchone()["count"]

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

    with get_db_connection() as conn:
        book_list = conn.execute(
            """
            SELECT
                b.*,
                b.quantity - (
                    SELECT COUNT(*)
                    FROM issues i
                    WHERE i.book_id = b.id
                    AND i.status = 'Issued'
                ) AS available
            FROM books b
            WHERE b.title ILIKE %s
               OR b.author ILIKE %s
               OR COALESCE(b.category, '') ILIKE %s
            ORDER BY b.id DESC
            """,
            (f"%{search}%", f"%{search}%", f"%{search}%")
        ).fetchall()

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

        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO books (title, author, category, quantity)
                VALUES (%s, %s, %s, %s)
                """,
                (title, author, category, quantity)
            )

        flash("Book added successfully!")
        return redirect(url_for("books"))

    return render_template("add_book.html")


# Register a student
@app.route("/students", methods=["GET", "POST"])
def students():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()

        if not name or not email or "@" not in email:
            flash("Please enter a valid name and email.")
            return redirect(url_for("students"))

        try:
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO students (name, email) VALUES (%s, %s)",
                    (name, email)
                )

            flash("Student registered successfully!")

        except psycopg.errors.UniqueViolation:
            flash("This email is already registered.")

        return redirect(url_for("students"))

    with get_db_connection() as conn:
        student_list = conn.execute(
            "SELECT * FROM students ORDER BY name"
        ).fetchall()

    return render_template("students.html", students=student_list)


# Issue a book
@app.route("/issue", methods=["GET", "POST"])
def issue_book():
    if request.method == "POST":
        try:
            book_id = int(request.form.get("book_id", "0"))
            student_id = int(request.form.get("student_id", "0"))
        except ValueError:
            flash("Please select a valid book and student.")
            return redirect(url_for("issue_book"))

        with get_db_connection() as conn:
            book = conn.execute(
                "SELECT * FROM books WHERE id = %s",
                (book_id,)
            ).fetchone()

            student = conn.execute(
                "SELECT * FROM students WHERE id = %s",
                (student_id,)
            ).fetchone()

            if not book or not student:
                flash("Selected book or student does not exist.")
                return redirect(url_for("issue_book"))

            issued_count = conn.execute(
                """
                SELECT COUNT(*) AS count FROM issues
                WHERE book_id = %s AND status = 'Issued'
                """,
                (book_id,)
            ).fetchone()["count"]

            if issued_count >= book["quantity"]:
                flash("No copies of this book are currently available.")
                return redirect(url_for("issue_book"))

            conn.execute(
                """
                INSERT INTO issues (book_id, student_id)
                VALUES (%s, %s)
                """,
                (book_id, student_id)
            )

        flash("Book issued successfully!")
        return redirect(url_for("records"))

    with get_db_connection() as conn:
        book_list = conn.execute(
            "SELECT * FROM books ORDER BY title"
        ).fetchall()

        student_list = conn.execute(
            "SELECT * FROM students ORDER BY name"
        ).fetchall()

    return render_template(
        "issue.html",
        books=book_list,
        students=student_list
    )


# View borrowing records and return books
@app.route("/records", methods=["GET", "POST"])
def records():
    if request.method == "POST":
        try:
            issue_id = int(request.form.get("issue_id", "0"))
        except ValueError:
            flash("Invalid borrowing record.")
            return redirect(url_for("records"))

        with get_db_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE issues
                SET status = 'Returned', return_date = CURRENT_DATE
                WHERE id = %s AND status = 'Issued'
                """,
                (issue_id,)
            )

            updated = cursor.rowcount

        if updated:
            flash("Book returned successfully!")
        else:
            flash("Record not found or book already returned.")

        return redirect(url_for("records"))

    with get_db_connection() as conn:
        issue_list = conn.execute(
            """
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
            """
        ).fetchall()

    return render_template("records.html", records=issue_list)


# Delete a book if it has no borrowing history
@app.route("/delete/<int:book_id>", methods=["POST"])
def delete_book(book_id):
    with get_db_connection() as conn:
        history = conn.execute(
            "SELECT COUNT(*) AS count FROM issues WHERE book_id = %s",
            (book_id,)
        ).fetchone()["count"]

        if history:
            flash("This book has borrowing records and cannot be deleted.")
            return redirect(url_for("books"))

        conn.execute(
            "DELETE FROM books WHERE id = %s",
            (book_id,)
        )

    flash("Book deleted successfully!")
    return redirect(url_for("books"))


if __name__ == "__main__":
    app.run(debug=True)