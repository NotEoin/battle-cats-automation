"""The live page's server: it answers this computer's own page and no other."""

import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from bcgacha import liveview


class _View:
    """Just enough of a LiveView to take a run request."""

    def __init__(self):
        self.submitted = []

    def submit(self, body):
        self.submitted.append(body)
        return True, "started"


@pytest.fixture
def server():
    view = _View()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), liveview.make_handler(view))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield view, httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _post(port, headers):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/api/run", body=json.dumps({"roll": True}),
                 headers={"Content-Type": "text/plain", **headers})
    status = conn.getresponse().status
    conn.close()
    return status


def test_a_run_from_the_page_itself_is_taken(server):
    view, port = server
    assert _post(port, {"Origin": f"http://127.0.0.1:{port}"}) == 200
    assert view.submitted == [{"roll": True}]


def test_a_run_posted_by_another_site_is_refused(server):
    """Regression: any web page could start a run that spends tickets."""
    view, port = server
    assert _post(port, {"Origin": "https://example.com"}) == 403
    assert view.submitted == []


def test_a_request_naming_another_host_is_refused(server):
    """Regression: a DNS-rebinding page could reach the API under its own name."""
    view, port = server
    assert _post(port, {"Host": f"evil.example:{port}"}) == 403
    assert view.submitted == []
