"""Start PaySignal locally:  python run.py   ->  http://127.0.0.1:5050"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from paysignal.app import create_app  # noqa: E402  (needs the env loaded first)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5050)), debug=False)
