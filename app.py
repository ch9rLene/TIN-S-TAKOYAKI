"""Tin's Takoyaki - simple order tracker (Flask + SQLite).

Run:
    pip install -r requirements.txt
    flask --app app run --host 0.0.0.0 --port 5000
Then open http://<IP-ng-computer-mo>:5000 sa phone (same WiFi).
"""
import csv
import io
import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, url_for)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TAKOYAKI_DB", os.path.join(BASE_DIR, "takoyaki.db"))
TZ = ZoneInfo("Asia/Manila")

STATUSES = ["Pending", "Niluluto", "Ready", "Nakuha"]
PAY_METHODS = ["Cash", "GCash"]
PACKAGING = ["Plastic", "Box"]

DEFAULT_MENU = [
    ("Veggies", 35, 65),
    ("Crabstick", 45, 85),
    ("Ham", 45, 85),
    ("Cheese", 45, 85),
    ("Ham & Cheese", 55, 105),
    ("Crab & Cheese", 55, 105),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS menu (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name   TEXT NOT NULL UNIQUE,
    p4     INTEGER NOT NULL,
    p8     INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    sort   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    queue_no   INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    customer   TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    pay_method TEXT NOT NULL DEFAULT 'Cash',
    paid       INTEGER NOT NULL DEFAULT 1,
    packaging  TEXT NOT NULL DEFAULT 'Plastic',
    status     TEXT NOT NULL DEFAULT 'Pending',
    waiting    INTEGER NOT NULL DEFAULT 0,
    deleted    INTEGER NOT NULL DEFAULT 0,
    total      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_orders_day ON orders(day);
CREATE TABLE IF NOT EXISTS order_items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    name     TEXT NOT NULL,
    size     INTEGER,
    spicy    INTEGER NOT NULL DEFAULT 0,
    price    INTEGER NOT NULL,
    custom   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
"""

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "palitan-mo-ito-sa-production")


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    if db.execute("SELECT COUNT(*) FROM menu").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO menu (name, p4, p8, sort) VALUES (?, ?, ?, ?)",
            [(n, a, b, i) for i, (n, a, b) in enumerate(DEFAULT_MENU)],
        )
    db.commit()


with app.app_context():
    init_db()


# ----------------------------------------------------------------- helpers
def now():
    return datetime.now(TZ)


def today():
    return now().date().isoformat()


def parse_day(value):
    try:
        return datetime.strptime(value or "", "%Y-%m-%d").date().isoformat()
    except ValueError:
        return today()


def fmt_time(iso):
    return datetime.fromisoformat(iso).strftime("%I:%M %p").lstrip("0")


def fmt_day(day):
    return datetime.strptime(day, "%Y-%m-%d").strftime("%a, %b %d")


def safe_next(default_endpoint="orders"):
    target = request.form.get("next") or ""
    if target.startswith("/") and not target.startswith("//"):
        return target
    return url_for(default_endpoint)


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@app.context_processor
def inject_globals():
    return {"fmt_day": fmt_day, "STATUSES": STATUSES,
            "PAY_METHODS": PAY_METHODS, "PACKAGING": PACKAGING}


def load_orders(day):
    """All non-deleted orders of a day, newest first, with their lines."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM orders WHERE day = ? AND deleted = 0 ORDER BY queue_no DESC",
        (day,),
    ).fetchall()
    by_order = {}
    if rows:
        ids = [r["id"] for r in rows]
        q = "SELECT * FROM order_items WHERE order_id IN (%s) ORDER BY id" % ",".join("?" * len(ids))
        for it in db.execute(q, ids):
            d = dict(it)
            d["label"] = d["name"] if d["custom"] else "%s · %d pcs" % (d["name"], d["size"])
            by_order.setdefault(it["order_id"], []).append(d)
    result = []
    for r in rows:
        o = dict(r)
        o["lines"] = by_order.get(r["id"], [])
        o["spicy"] = any(l["spicy"] for l in o["lines"])
        o["time"] = fmt_time(r["created_at"])
        idx = STATUSES.index(r["status"]) if r["status"] in STATUSES else 0
        o["next_status"] = STATUSES[idx + 1] if idx + 1 < len(STATUSES) else None
        result.append(o)
    return result


# ------------------------------------------------------------- new order
@app.route("/")
def new_order():
    db = get_db()
    menu = [
        {"id": r["id"], "name": r["name"], "p4": r["p4"], "p8": r["p8"]}
        for r in db.execute("SELECT * FROM menu WHERE active = 1 ORDER BY sort, id")
    ]
    next_no = db.execute(
        "SELECT COALESCE(MAX(queue_no), 0) + 1 FROM orders WHERE day = ?", (today(),)
    ).fetchone()[0]
    return render_template("new_order.html", menu=menu, next_no=next_no,
                           today_label=fmt_day(today()))


@app.post("/api/orders")
def api_create_order():
    data = request.get_json(silent=True) or {}
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify(error="Walang laman ang order."), 400

    db = get_db()
    menu = {r["name"]: r for r in db.execute("SELECT * FROM menu")}
    clean, total = [], 0
    for it in raw_items:
        if not isinstance(it, dict):
            return jsonify(error="Mali ang item."), 400
        if it.get("custom"):
            name = str(it.get("name", "")).strip()[:60]
            price = to_int(it.get("price"), -1)
            if not name or price < 0:
                return jsonify(error="Kulang ang pangalan o presyo ng custom item."), 400
            clean.append((name, None, 0, price, 1))
        else:
            row = menu.get(it.get("name"))
            size = to_int(it.get("size"))
            if row is None or size not in (4, 8):
                return jsonify(error="Hindi kilalang flavor o laki."), 400
            price = row["p4"] if size == 4 else row["p8"]
            clean.append((row["name"], size, 1 if it.get("spicy") else 0, price, 0))
        total += price

    pay = data.get("pay_method") if data.get("pay_method") in PAY_METHODS else "Cash"
    pack = data.get("packaging") if data.get("packaging") in PACKAGING else "Plastic"
    stamp = now()
    day = stamp.date().isoformat()

    with db:
        queue_no = db.execute(
            "SELECT COALESCE(MAX(queue_no), 0) + 1 FROM orders WHERE day = ?", (day,)
        ).fetchone()[0]
        cur = db.execute(
            """INSERT INTO orders (day, queue_no, created_at, customer, note,
                                   pay_method, paid, packaging, total)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (day, queue_no, stamp.isoformat(timespec="seconds"),
             str(data.get("customer", "")).strip()[:120],
             str(data.get("note", "")).strip()[:200],
             pay, 1 if data.get("paid") else 0, pack, total),
        )
        order_id = cur.lastrowid
        db.executemany(
            "INSERT INTO order_items (order_id, name, size, spicy, price, custom) VALUES (?, ?, ?, ?, ?, ?)",
            [(order_id,) + c for c in clean],
        )
    return jsonify(id=order_id, queue_no=queue_no, total=total), 201


# ----------------------------------------------------------- order list
@app.route("/orders")
def orders():
    day = parse_day(request.args.get("day"))
    flt = request.args.get("filter", "all")
    all_orders = load_orders(day)

    counts = {"all": len(all_orders),
              "unpaid": sum(1 for o in all_orders if not o["paid"]),
              "waiting": sum(1 for o in all_orders if o["waiting"])}
    for s in STATUSES:
        counts[s] = sum(1 for o in all_orders if o["status"] == s)

    def keep(o):
        if flt == "unpaid":
            return not o["paid"]
        if flt == "waiting":
            return bool(o["waiting"])
        if flt in STATUSES:
            return o["status"] == flt
        return True

    visible = [o for o in all_orders if keep(o)]
    undo = None
    undo_id = request.args.get("undo", type=int)
    if undo_id:
        undo = get_db().execute(
            "SELECT id, queue_no FROM orders WHERE id = ? AND deleted = 1", (undo_id,)
        ).fetchone()

    return render_template(
        "orders.html", orders=visible, counts=counts, day=day, flt=flt,
        total=sum(o["total"] for o in all_orders), undo=undo,
        saved=request.args.get("saved", type=int), is_today=(day == today()),
    )


def get_order_or_404(order_id):
    row = get_db().execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        abort(404)
    return row


@app.post("/orders/<int:order_id>/status")
def set_status(order_id):
    get_order_or_404(order_id)
    status = request.form.get("status")
    if status not in STATUSES:
        abort(400)
    db = get_db()
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    if status == "Nakuha":
        db.execute("UPDATE orders SET waiting = 0 WHERE id = ?", (order_id,))
    db.commit()
    return redirect(safe_next())


@app.post("/orders/<int:order_id>/paid")
def toggle_paid(order_id):
    get_order_or_404(order_id)
    db = get_db()
    db.execute("UPDATE orders SET paid = 1 - paid WHERE id = ?", (order_id,))
    db.commit()
    return redirect(safe_next())


@app.post("/orders/<int:order_id>/waiting")
def toggle_waiting(order_id):
    get_order_or_404(order_id)
    db = get_db()
    db.execute("UPDATE orders SET waiting = 1 - waiting WHERE id = ?", (order_id,))
    db.commit()
    return redirect(safe_next())


@app.post("/orders/<int:order_id>/delete")
def delete_order(order_id):
    row = get_order_or_404(order_id)
    db = get_db()
    db.execute("UPDATE orders SET deleted = 1 WHERE id = ?", (order_id,))
    db.commit()
    return redirect(url_for("orders", day=row["day"], undo=order_id))


@app.post("/orders/<int:order_id>/restore")
def restore_order(order_id):
    row = get_order_or_404(order_id)
    db = get_db()
    db.execute("UPDATE orders SET deleted = 0 WHERE id = ?", (order_id,))
    db.commit()
    return redirect(url_for("orders", day=row["day"]))


@app.route("/orders/<int:order_id>/edit", methods=["GET", "POST"])
def edit_order(order_id):
    row = get_order_or_404(order_id)
    if request.method == "POST":
        pay = request.form.get("pay_method")
        pack = request.form.get("packaging")
        db = get_db()
        db.execute(
            "UPDATE orders SET customer = ?, note = ?, pay_method = ?, packaging = ? WHERE id = ?",
            (request.form.get("customer", "").strip()[:120],
             request.form.get("note", "").strip()[:200],
             pay if pay in PAY_METHODS else row["pay_method"],
             pack if pack in PACKAGING else row["packaging"],
             order_id),
        )
        db.commit()
        return redirect(url_for("orders", day=row["day"]))
    return render_template("edit_order.html", o=row)


# --------------------------------------------------------------- summary
@app.route("/summary")
def summary():
    day = parse_day(request.args.get("day"))
    db = get_db()
    t = db.execute(
        """SELECT COUNT(*) AS n,
                  COALESCE(SUM(total), 0) AS total,
                  COALESCE(SUM(CASE WHEN paid = 1 THEN total END), 0) AS paid_total,
                  COALESCE(SUM(CASE WHEN paid = 0 THEN total END), 0) AS unpaid_total,
                  COALESCE(SUM(CASE WHEN paid = 0 THEN 1 END), 0) AS unpaid_n,
                  COALESCE(SUM(CASE WHEN paid = 1 AND pay_method = 'Cash' THEN total END), 0) AS cash,
                  COALESCE(SUM(CASE WHEN paid = 1 AND pay_method = 'GCash' THEN total END), 0) AS gcash,
                  COALESCE(SUM(waiting), 0) AS waiting_n
           FROM orders WHERE day = ? AND deleted = 0""",
        (day,),
    ).fetchone()
    spicy_n = db.execute(
        """SELECT COUNT(DISTINCT i.order_id) FROM order_items i
           JOIN orders o ON o.id = i.order_id
           WHERE o.day = ? AND o.deleted = 0 AND i.spicy = 1""",
        (day,),
    ).fetchone()[0]
    flavors = [dict(r) for r in db.execute(
        """SELECT i.name AS name, SUM(i.size) AS pcs FROM order_items i
           JOIN orders o ON o.id = i.order_id
           WHERE o.day = ? AND o.deleted = 0 AND i.custom = 0
           GROUP BY i.name ORDER BY pcs DESC, i.name""",
        (day,),
    )]
    top = max((f["pcs"] for f in flavors), default=1)
    for f in flavors:
        f["pct"] = round(f["pcs"] * 100 / top)
    unpaid_nos = [r["queue_no"] for r in db.execute(
        "SELECT queue_no FROM orders WHERE day = ? AND deleted = 0 AND paid = 0 ORDER BY queue_no",
        (day,),
    )]
    waiting_nos = [r["queue_no"] for r in db.execute(
        "SELECT queue_no FROM orders WHERE day = ? AND deleted = 0 AND waiting = 1 ORDER BY queue_no",
        (day,),
    )]
    return render_template(
        "summary.html", day=day, t=t, spicy_n=spicy_n, flavors=flavors,
        pcs_total=sum(f["pcs"] for f in flavors),
        unpaid_nos=unpaid_nos, waiting_nos=waiting_nos,
    )


@app.route("/export.csv")
def export_csv():
    day = parse_day(request.args.get("day"))
    out = io.StringIO()
    out.write("﻿")  # para mabasa nang tama ng Excel
    w = csv.writer(out)
    w.writerow(["Day", "Queue", "Oras", "Customer", "Laman", "Notes", "Total",
                "Bayad", "Paraan", "Packaging", "Status", "Spicy", "Di pa binalikan"])
    for o in reversed(load_orders(day)):
        w.writerow([
            day, o["queue_no"], o["time"], o["customer"],
            "; ".join(l["label"] + (" (spicy)" if l["spicy"] else "") for l in o["lines"]),
            o["note"], o["total"], "Oo" if o["paid"] else "Hindi", o["pay_method"],
            o["packaging"], o["status"], "Oo" if o["spicy"] else "Hindi",
            "Oo" if o["waiting"] else "Hindi",
        ])
    return Response(
        out.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="takoyaki-%s.csv"' % day},
    )


# -------------------------------------------------------------- settings
@app.route("/settings", methods=["GET", "POST"])
def settings():
    db = get_db()
    if request.method == "POST":
        for r in db.execute("SELECT id FROM menu").fetchall():
            p4 = to_int(request.form.get("p4_%d" % r["id"]))
            p8 = to_int(request.form.get("p8_%d" % r["id"]))
            if p4 is None or p8 is None or p4 < 0 or p8 < 0:
                flash("Mali ang isa sa mga presyo. Walang na-save.")
                return redirect(url_for("settings"))
        for r in db.execute("SELECT id FROM menu").fetchall():
            db.execute(
                "UPDATE menu SET p4 = ?, p8 = ?, active = ? WHERE id = ?",
                (to_int(request.form.get("p4_%d" % r["id"])),
                 to_int(request.form.get("p8_%d" % r["id"])),
                 1 if request.form.get("active_%d" % r["id"]) else 0, r["id"]),
            )
        db.commit()
        flash("Na-save ang menu.")
        return redirect(url_for("settings"))
    menu = db.execute("SELECT * FROM menu ORDER BY sort, id").fetchall()
    return render_template("settings.html", menu=menu)


@app.post("/settings/add")
def add_flavor():
    name = request.form.get("name", "").strip()[:60]
    p4, p8 = to_int(request.form.get("p4")), to_int(request.form.get("p8"))
    if not name or p4 is None or p8 is None or p4 < 0 or p8 < 0:
        flash("Kulang o mali ang pangalan o presyo ng bagong flavor.")
        return redirect(url_for("settings"))
    db = get_db()
    try:
        db.execute(
            "INSERT INTO menu (name, p4, p8, sort) VALUES (?, ?, ?, (SELECT COALESCE(MAX(sort), 0) + 1 FROM menu))",
            (name, p4, p8),
        )
        db.commit()
        flash("Naidagdag ang %s." % name)
    except sqlite3.IntegrityError:
        flash("Mayroon nang flavor na %s." % name)
    return redirect(url_for("settings"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
