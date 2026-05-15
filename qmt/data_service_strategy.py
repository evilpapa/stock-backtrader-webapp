# coding: gbk

"""Start the local QMT data web service from a QMT strategy."""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qmt.data_gateway import start_qmt_data_service, stop_qmt_data_service


HOST = os.environ.get("QMT_DATA_SERVICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("QMT_DATA_SERVICE_PORT", "8765"))
TOKEN = os.environ.get("QMT_DATA_SERVICE_TOKEN") or None


def init(ContextInfo):
    status = start_qmt_data_service(ContextInfo, host=HOST, port=PORT, token=TOKEN)
    print(
        "[qmt_data_service] started host={0} port={1} auth_required={2}".format(
            status["host"],
            status["port"],
            status["auth_required"],
        )
    )


def handlebar(ContextInfo):
    return


def stop(ContextInfo):
    stop_qmt_data_service()
    print("[qmt_data_service] stopped")
