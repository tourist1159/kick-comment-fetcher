from http.server import SimpleHTTPRequestHandler, HTTPServer

class CORSRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        return super().end_headers()

if __name__ == "__main__":
    PORT = 8000
    with HTTPServer(("localhost", PORT), CORSRequestHandler) as httpd:
        print(f"Serving with CORS enabled on http://localhost:{PORT}")
        httpd.serve_forever()
