import os
import socket
import time

import psycopg2
import redis
from flask import Flask, jsonify, request

app = Flask(__name__)


def read_secret(name):
    # Docker secrets arrive as files; fall back to a plain variable for local use
    path = os.environ.get(name + "_FILE")
    if path:
        with open(path) as f:
            return f.read().strip()
    return os.environ[name]


cache = redis.Redis(
    host=os.environ.get("REDIS_HOST", "redis"),
    port=6379,
    socket_connect_timeout=2,
    decode_responses=True,
)


def connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        dbname=os.environ.get("DB_NAME", "inventory"),
        user=os.environ.get("DB_USER", "inventory"),
        password=read_secret("DB_PASSWORD"),
        connect_timeout=3,
    )


def run(sql, params=None, fetch=False):
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if fetch else None
    finally:
        conn.close()


def init_db():
    for _ in range(20):
        try:
            conn = connect()
            try:
                with conn, conn.cursor() as cur:
                    # two gunicorn workers start together; the lock stops a race
                    cur.execute("SELECT pg_advisory_xact_lock(42)")
                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS items ("
                        "id SERIAL PRIMARY KEY, name TEXT NOT NULL, "
                        "quantity INT NOT NULL DEFAULT 0)"
                    )
            finally:
                conn.close()
            return
        except psycopg2.OperationalError:
            time.sleep(1)
    raise RuntimeError("database not reachable")


init_db()


@app.get("/")
def index():
    return jsonify(service="docker-deep-dive", container=socket.gethostname())


@app.get("/health")
def health():
    try:
        cache.ping()
        run("SELECT 1", fetch=True)
        return jsonify(status="ok")
    except Exception:
        return jsonify(status="dependency unreachable"), 503


@app.get("/hits")
def hits():
    return jsonify(hits=cache.incr("hits"), container=socket.gethostname())


@app.get("/items")
def list_items():
    rows = run("SELECT id, name, quantity FROM items ORDER BY id", fetch=True)
    return jsonify([{"id": r[0], "name": r[1], "quantity": r[2]} for r in rows])


@app.post("/items")
def add_item():
    data = request.get_json(force=True)
    rows = run(
        "INSERT INTO items (name, quantity) VALUES (%s, %s) RETURNING id",
        (data["name"], data.get("quantity", 0)),
        fetch=True,
    )
    return jsonify(id=rows[0][0]), 201
