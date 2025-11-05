
from flask import Flask
import os

keep_alive_app = Flask(__name__)

@keep_alive_app.route('/', methods=['GET', 'POST'])
def webhook() -> str:
    return "Bot alive! No sleep pls~ 😴"

def run_keep_alive():
    port = int(os.environ.get('PORT', 8080))
    keep_alive_app.run(host='0.0.0.0', port=port, debug=False)
