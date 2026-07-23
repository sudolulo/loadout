#!/usr/bin/env python3
"""Redist interception server for headless FitGirl/Inno installs.

FitGirl repacks fetch VC++/DirectX/.NET redistributables from download.microsoft.com
during install; under Wine (especially in an LXC) those requests get no route and the
installer hard-blocks. Point the Wine prefix's WinINet proxy at this server and it answers
every request with a genuine Microsoft vcredist -- the download "succeeds", the installer
runs it (harmless; Proton provides all runtimes on the Deck anyway) and proceeds to unpack.

Serves the real file by basename when cached, else the vcredist as a universal stand-in.
Prefix-only interception (a proxy setting inside our own sandbox) -- no iptables, no
/etc/hosts, nothing touched system-wide.
"""
import http.server, socketserver, sys, os

CACHE = os.environ.get("REDIST_CACHE", "/home/dev/wizard-test/redist-cache")
FALLBACK = os.path.join(CACHE, "vcredist_2008_x86.exe")
PORT = int(os.environ.get("REDIST_PORT", "8899"))


class H(http.server.BaseHTTPRequestHandler):
    def _serve(self, body=True):
        fn = os.path.basename(self.path.split("?")[0])          # works for proxy-style URLs too
        path = os.path.join(CACHE, fn)
        if not os.path.isfile(path):
            path = FALLBACK
        data = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if body:
            self.wfile.write(data)
        sys.stderr.write("SERVED %s -> %s (%d bytes)\n"
                         % (self.path, os.path.basename(path), len(data)))
        sys.stderr.flush()

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)

    def log_message(self, *a):
        pass


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), H) as s:
    sys.stderr.write("redist-server on 127.0.0.1:%d, cache=%s\n" % (PORT, CACHE))
    sys.stderr.flush()
    s.serve_forever()
