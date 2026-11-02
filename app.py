import socket

from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/")
def index():
    # the hostname inside a container is the container ID
    return jsonify(service="docker-deep-dive", container=socket.gethostname())


@app.get("/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
