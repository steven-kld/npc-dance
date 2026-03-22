import logging
from pathlib import Path

LOG_FILE = Path(__file__).parent / "agent.log"


class Logger:
    def __init__(self, clear: bool = True):
        self._log = logging.getLogger("agent")
        if not self._log.handlers:
            if clear:
                LOG_FILE.write_text("")
            self._log.setLevel(logging.INFO)
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            fh = logging.FileHandler(LOG_FILE)
            fh.setFormatter(fmt)
            sh = logging.StreamHandler()
            sh.setFormatter(fmt)
            self._log.addHandler(fh)
            self._log.addHandler(sh)

    def log(self, msg: str) -> None:
        self._log.info(msg)

    def error(self, msg: str) -> None:
        self._log.error(msg)
