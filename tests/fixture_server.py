"""Local native-GUI fixture: launch token, HttpOnly cookie, API and WebSocket.

The token is deliberately public fixture data, never a real Harness credential.
Run: python3 tests/fixture_server.py; connect to localhost:4317/?token=fixture-token
"""
import base64
import hashlib
import json
import struct
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

PAGE = rb'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Harness fixture</title>
<style>body{font:18px system-ui;padding:40px;background:#f6f8fc;color:#202936}button,input,a{margin:12px 12px 12px 0}pre{white-space:pre-wrap}</style>
<h1>Harness fixture</h1><p id="api">API loading</p><p id="socket">WebSocket loading</p>
<label>Text editing <input id="editor" value="Copy and paste here"></label><br>
<label>Upload a file <input id="upload" type="file"></label><span id="filename"></span><br>
<a href="/download" download="fixture.txt">Download fixture</a>
<a href="https://example.com" target="_blank">External link</a>
<button id="ipc">Check IPC isolation</button><pre id="ipc-result"></pre>
<button id="expire">Expire session</button>
<script>
fetch('/api/status').then(r=>r.json()).then(x=>document.querySelector('#api').textContent=x.status);
const socket=new WebSocket('ws://'+location.host+'/ws');
socket.onopen=()=>socket.send('hello');
socket.onmessage=e=>document.querySelector('#socket').textContent=e.data;
document.querySelector('#upload').onchange=e=>document.querySelector('#filename').textContent=e.target.files[0]?.name||'';
document.querySelector('#ipc').onclick=async()=>{let result=[];for(const command of ['get_snapshot','connect','cancel_connect','open_preferences','get_preferences','set_language','close_preferences','plugin:opener|open_url','plugin:event|listen']){
try{await window.__TAURI_INTERNALS__.invoke(command,{language:'en',address:'http://localhost:4317',url:'https://example.com',event:'connection-state',target:{kind:'Any'},handler:999});result.push(command+': UNEXPECTED ALLOWED');}
catch{result.push(command+': denied');}}document.querySelector('#ipc-result').textContent=result.join('\n');};
document.querySelector('#expire').onclick=()=>fetch('/expire',{method:'POST'}).then(()=>location.reload());
</script></html>'''

SCROLL_PAGE = rb'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Desktop scroll fixture</title>
<link rel="stylesheet" href="/shell.css">
<script src="/shell.js" defer></script><body></body></html>'''

SCROLL_CSS = rb'''
html,body,#root{height:100%;margin:0}
body{font:18px system-ui;background:#f6f8fc;color:#202936}
#frame{height:100%;display:grid;grid-template-columns:220px minmax(0,1fr);overflow:hidden}
#sidebar{overflow:auto;background:#e9edf5}
#conversation{min-height:0;min-width:0;display:flex;flex-direction:column;overflow:hidden}
header,footer{flex:none;padding:16px;background:#ffffff}
#messages{flex:1;min-height:0;overflow:auto;padding:16px}
.row{height:70px;padding:8px;box-sizing:border-box}
pre{width:2400px}
#outside-root{height:2000px;width:3000px}
'''

SCROLL_JS = rb'''
// Exercise an asynchronously created mount, as well as portalled body siblings.
setTimeout(()=>{
  const root=document.createElement('div');root.id='root';
  root.innerHTML='<div id="frame"><aside id="sidebar" tabindex="0"></aside><main id="conversation"><header>Desktop scroll fixture</header><section id="messages" tabindex="0"></section><footer><textarea id="composer" aria-label="Message">Message composer</textarea></footer></main></div>';
  for(let i=0;i<60;i++){
    for(const id of ['sidebar','messages']){
      const row=document.createElement('div');row.className='row';row.textContent=id+' '+i;
      root.querySelector('#'+id).append(row);
    }
  }
  const code=document.createElement('pre');code.textContent='Long code line '.repeat(160);
  root.querySelector('#messages').prepend(code);
  document.body.append(root);
  const portal=document.createElement('div');portal.id='outside-root';document.body.append(portal);
},120);
'''


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_args):
        pass  # Request URLs can contain launch tokens; never log them.

    def authorized(self):
        cookies = SimpleCookie(self.headers.get('Cookie', ''))
        return cookies.get('fixture_session') is not None and cookies['fixture_session'].value == 'browser-session'

    def respond(self, status, body=b'', content_type='text/plain', headers=()):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/slow':
            time.sleep(18)
            try:
                self.respond(200, b'Slow fixture')
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif parsed.path == '/forbidden':
            self.respond(403, b'Forbidden fixture')
        elif parsed.path in ('/', '/shell') and parse_qs(parsed.query).get('token') == ['fixture-token']:
            self.respond(303, headers=[('Location', parsed.path), ('Referrer-Policy', 'no-referrer'),
                ('Set-Cookie', 'fixture_session=browser-session; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400')])
        elif not self.authorized():
            self.respond(401, b'Authentication required')
        elif parsed.path == '/ws':
            self.websocket()
        elif parsed.path == '/api/status':
            self.respond(200, json.dumps({'status': 'API authenticated'}).encode(), 'application/json')
        elif parsed.path == '/download':
            self.respond(200, b'Harness desktop download fixture\n', headers=[('Content-Disposition', 'attachment; filename="fixture.txt"')])
        elif parsed.path == '/shell':
            self.respond(200, SCROLL_PAGE, 'text/html; charset=utf-8', headers=[
                ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'")])
        elif parsed.path == '/shell.css':
            self.respond(200, SCROLL_CSS, 'text/css')
        elif parsed.path == '/shell.js':
            self.respond(200, SCROLL_JS, 'application/javascript')
        elif parsed.path == '/':
            self.respond(200, PAGE, 'text/html; charset=utf-8')
        else:
            self.respond(404)

    def do_POST(self):
        if urlsplit(self.path).path == '/expire':
            self.respond(200, headers=[('Set-Cookie', 'fixture_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')])
        else:
            self.respond(404)

    def websocket(self):
        key = self.headers.get('Sec-WebSocket-Key', '')
        accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        self.send_response(101)
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', accept)
        self.end_headers()
        self.wfile.write(b'\x81\x17WebSocket authenticated')
        self.wfile.flush()
        try:
            while True:
                header = self.rfile.read(2)
                if len(header) < 2 or header[0] & 15 == 8:
                    break
                length = header[1] & 127
                if length == 126:
                    length = struct.unpack('!H', self.rfile.read(2))[0]
                elif length == 127:
                    length = struct.unpack('!Q', self.rfile.read(8))[0]
                if length > 65536:
                    break
                mask = self.rfile.read(4) if header[1] & 128 else b''
                data = self.rfile.read(length)
                if mask:
                    data = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
                if not data:
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass


if __name__ == '__main__':
    print('Fixture ready: http://localhost:4317/?token=fixture-token', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 4317), Handler).serve_forever()
