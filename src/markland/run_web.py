"""Run the Markland web viewer."""

import logging

import uvicorn

from markland.config import get_config
from markland.db import init_db
from markland.web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("markland.web")

config = get_config()
db_conn = init_db(config.db_path)
app = create_app(db_conn)


if __name__ == "__main__":
    logger.info(
        "Starting Markland web viewer on port %d (db: %s)",
        config.web_port,
        config.db_path,
    )
    uvicorn.run(app, host="127.0.0.1", port=config.web_port)
