"""Native GTK/WebKit smoke test in an isolated Xvfb Docker session.

Uses WebKitGTK's WebDriver service against the compiled application, not a browser
preview. All authentication values here belong to the disposable fixture server.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get('DSH_TEST_BINARY', str(ROOT / 'src-tauri/target/release/deepseek-harness-desktop')))
PROCESS = os.environ.get('DSH_TEST_PROCESS', str(BINARY))
DRIVER = 'http://127.0.0.1:4444'


def request(method, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = Request(DRIVER + path, body, {'Content-Type': 'application/json'}, method=method)
    try:
        with urlopen(req, timeout=40) as response:
            result = json.load(response)
    except HTTPError as error:
        result = json.load(error)
    value = result.get('value')
    if isinstance(value, dict) and value.get('error'):
        raise RuntimeError(value['error'] + ': ' + value.get('message', '')[:500])
    return value


def wait_for(callback, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = callback()
            if value:
                return value
        except (URLError, RuntimeError):
            pass
        time.sleep(0.2)
    raise AssertionError('Native condition timed out')


def main():
    with tempfile.TemporaryDirectory(prefix='dsh-native-') as profile:
        # Capture OS browser launches in this disposable profile. No real browser
        # or outbound connection is needed to verify native external-link routing.
        launch_directory = Path(profile) / 'bin'
        launch_directory.mkdir()
        launch_log = Path(profile) / 'external-links.txt'
        launcher = launch_directory / 'xdg-open'
        launcher.write_text('#!/bin/sh\nprintf \'%s\\n\' "$1" >> "$DSH_EXTERNAL_LOG"\n')
        launcher.chmod(0o755)
        environment = os.environ.copy()
        environment.update({
            'PATH': str(launch_directory) + os.pathsep + environment.get('PATH', ''),
            'DSH_EXTERNAL_LOG': str(launch_log),
            'TAURI_WEBVIEW_AUTOMATION': 'true',
            'XDG_CONFIG_HOME': profile + '/config',
            'XDG_DATA_HOME': profile + '/data',
            'XDG_CACHE_HOME': profile + '/cache',
            # LANGUAGE determines the app's preferred language. Keep a locale
            # installed in this minimal image so GTK writes UTF-8 X11 titles.
            'LANGUAGE': 'ru_RU', 'LC_ALL': 'C.UTF-8', 'LANG': 'C.UTF-8',
        })
        fixture = subprocess.Popen(['python3', 'tests/fixture_server.py'], cwd=ROOT)
        certificate = profile + '/certificate.pem'
        private_key = profile + '/key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-days', '1', '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
            '-keyout', private_key, '-out', certificate], check=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        tls_fixture = subprocess.Popen(['python3', '-c', '''import ssl,sys
from tests.fixture_server import Handler, ThreadingHTTPServer
server=ThreadingHTTPServer(('127.0.0.1',4319),Handler)
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(sys.argv[1],sys.argv[2])
server.socket=context.wrap_socket(server.socket,server_side=True)
server.serve_forever()''', certificate, private_key], cwd=ROOT, stdout=subprocess.DEVNULL)
        driver = subprocess.Popen(['WebKitWebDriver', '--port=4444'], env=environment)
        session = None
        try:
            wait_for(lambda: request('GET', '/status')['ready'])
            created = request('POST', '/session', {'capabilities': {'alwaysMatch': {
                'browserName': 'wry', 'webkitgtk:browserOptions': {'binary': str(BINARY)}
            }}})
            session = created['sessionId']
            prefix = '/session/' + session

            def script(code, arguments=None):
                return request('POST', prefix + '/execute/sync', {'script': code, 'args': arguments or []})

            def asynchronous(code, arguments=None):
                return request('POST', prefix + '/execute/async', {'script': code, 'args': arguments or []})

            def select_window(text):
                for handle in request('GET', prefix + '/window/handles'):
                    request('POST', prefix + '/window', {'handle': handle})
                    if text in (script('return document.body.innerText') or ''):
                        return handle
                return None

            def shortcut(keys):
                windows = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--name',
                    '^DeepSeek Harness Desktop$'], text=True).splitlines()
                assert len(windows) == 1, 'Only one primary window should be visible'
                subprocess.run(['xdotool', 'windowfocus', '--sync', windows[0]], check=True)
                subprocess.run(['xdotool', 'key', '--clearmodifiers', keys], check=True)

            def switch_server():
                shortcut('ctrl+l')
                return wait_for(lambda: select_window('Адрес сервера'))

            def local_message(text):
                request('POST', prefix + '/window', {'handle': local})
                return text in script('return document.body.innerText')

            def save_dialog():
                result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name',
                    '^Сохранить файл$'], text=True, capture_output=True)
                return result.stdout.splitlines() if result.returncode == 0 else []

            def download(destination=None, headers=False):
                select_window('Harness fixture')
                wait_for(lambda: script('return document.visibilityState') == 'visible')
                if headers:
                    script('document.querySelector("a[download]").removeAttribute("download")')
                element = request('POST', prefix + '/element', {'using': 'css selector', 'value': 'a[href="/download"]'})
                element_id = element['element-6066-11e4-a52e-4f735466cecf']
                # WebKit requires a trusted user gesture for downloads. The click
                # can await the modal dialog, so respond from the test's UI thread.
                with ThreadPoolExecutor(max_workers=1) as clicks:
                    clicked = clicks.submit(request, 'POST', prefix + '/element/' + element_id + '/click', {})
                    try:
                        def dialog_or_click_error():
                            if clicked.done():
                                clicked.result()
                            return save_dialog()
                        dialog = wait_for(dialog_or_click_error)[0]
                    except AssertionError:
                        windows = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '.'], text=True, capture_output=True)
                        for window in windows.stdout.splitlines():
                            title = subprocess.run(['xdotool', 'getwindowname', window], text=True, capture_output=True)
                            print('Native download diagnostic: ' + title.stdout.strip(), flush=True)
                        print('Download click completed: ' + str(clicked.done()), flush=True)
                        print('Page after click: ' + script('return location.pathname + " / " + document.body.innerText'), flush=True)
                        raise
                    subprocess.run(['xdotool', 'windowfocus', '--sync', dialog], check=True)
                    if destination is None:
                        subprocess.run(['xdotool', 'key', 'Escape'], check=True)
                    else:
                        subprocess.run(['xdotool', 'key', 'ctrl+l'], check=True)
                        time.sleep(0.5)
                        subprocess.run(['xdotool', 'key', 'ctrl+a'], check=True)
                        time.sleep(0.5)
                        subprocess.run(['xdotool', 'type', '--clearmodifiers', '--delay', '80', str(destination)], check=True)
                        subprocess.run(['xdotool', 'key', 'Return'], check=True)
                        time.sleep(0.3)
                        if save_dialog():
                            subprocess.run(['xdotool', 'key', 'Return'], check=True)
                        wait_for(lambda: destination.exists() and destination.read_bytes() == b'Harness desktop download fixture\n')
                    wait_for(lambda: not save_dialog())
                    clicked.result(timeout=15)

            local = wait_for(lambda: select_window('Адрес сервера'), seconds=60)
            assert script('return document.querySelector("#server-url").value') == ''
            artifact = ROOT / 'artifacts/linux'
            artifact.mkdir(parents=True, exist_ok=True)

            def screenshot(name):
                encoded = request('GET', prefix + '/screenshot')
                (artifact / name).write_bytes(base64.b64decode(encoded))

            screenshot('native-connection.png')

            def connect_fixture(address):
                request('POST', prefix + '/window', {'handle': local})
                script('document.querySelector("#server-url").value=arguments[0];document.querySelector("#connect-form").requestSubmit()', [address])

            connect_fixture('localhost:4317/?token=fixture-token')
            remote = wait_for(lambda: select_window('Harness fixture'))
            wait_for(lambda: 'API authenticated' in script('return document.body.innerText'))
            wait_for(lambda: 'WebSocket authenticated' in script('return document.body.innerText'))
            assert 'token=' not in request('GET', prefix + '/url')
            for command in ['get_snapshot', 'connect', 'cancel_connect', 'open_preferences', 'get_preferences', 'set_language', 'close_preferences', 'plugin:opener|open_url', 'plugin:event|listen']:
                outcome = asynchronous('''const done=arguments[arguments.length-1];
                  window.__TAURI_INTERNALS__.invoke(arguments[0],{address:'http://localhost:4317',
                    language:'en',url:'https://example.com',event:'connection-state',target:{kind:'Any'},handler:999})
                  .then(()=>done('allowed'),error=>done(String(error)));''', [command])
                denied = any(word in outcome.lower() for word in ('not allowed', 'forbidden', 'denied'))
                # Release builds prune plugin commands with no capability.
                removed = command.startswith('plugin:') and 'not found' in outcome.lower()
                assert denied or removed, command + ': ' + outcome
            time.sleep(0.3)
            screenshot('native-fixture.png')
            print('PASS: native form, token/cookie, API, WebSocket and IPC isolation', flush=True)

            external = request('POST', prefix + '/element', {'using': 'css selector', 'value': 'a[target="_blank"]'})
            identifier = external['element-6066-11e4-a52e-4f735466cecf']
            # A programmatic .click() has no trusted user gesture and WebKit may
            # block the popup before Wry receives its native new-window event.
            request('POST', prefix + '/element/' + identifier + '/click', {})
            wait_for(lambda: launch_log.exists() and launch_log.read_text().splitlines() == ['https://example.com/'])
            script('location.href="https://example.com/navigation"')
            wait_for(lambda: launch_log.read_text().splitlines() == ['https://example.com/', 'https://example.com/navigation'])
            assert request('GET', prefix + '/url').startswith('http://localhost:4317/')
            assert len(request('GET', prefix + '/window/handles')) == 2
            print('PASS: external new-window and navigation links use the native launcher without remote IPC', flush=True)

            upload = Path(profile) / 'upload.txt'
            upload.write_text('Native upload fixture\n')
            element = request('POST', prefix + '/element', {'using': 'css selector', 'value': '#upload'})
            element_id = element['element-6066-11e4-a52e-4f735466cecf']
            request('POST', prefix + '/element/' + element_id + '/value', {'text': str(upload)})
            wait_for(lambda: script('return document.querySelector("#filename").textContent') == 'upload.txt')

            script('document.querySelector("#editor").focus()')
            shortcut('ctrl+a')
            shortcut('ctrl+x')
            wait_for(lambda: script('return document.querySelector("#editor").value') == '')
            shortcut('ctrl+v')
            wait_for(lambda: script('return document.querySelector("#editor").value') == 'Copy and paste here')
            shortcut('ctrl+r')
            remote = wait_for(lambda: select_window('Harness fixture'))
            wait_for(lambda: 'API authenticated' in script('return document.body.innerText'))
            width = script('return document.documentElement.clientWidth')
            shortcut('ctrl+equal')
            wait_for(lambda: script('return document.documentElement.clientWidth') < width)
            shortcut('ctrl+0')
            wait_for(lambda: script('return document.documentElement.clientWidth') == width)
            print('PASS: upload, native clipboard and Ctrl+R', flush=True)
            download()

            # The desktop mount stays inside the viewport; panels retain native
            # wheel/keyboard scrolling, even under a strict server stylesheet CSP.
            local = switch_server()
            connect_fixture('localhost:4317/shell')
            remote = wait_for(lambda: select_window('Desktop scroll fixture'))
            wait_for(lambda: script('return document.visibilityState') == 'visible')

            def pinned_shell():
                return script('''const root=document.querySelector('#root');
                  const bounds=root.getBoundingClientRect();
                  window.scrollTo(1000,1000);root.scrollTo(1000,1000);
                  return [document.documentElement,document.body,root].every(element=>
                    getComputedStyle(element).overflow==='clip' &&
                    getComputedStyle(element).overscrollBehavior==='none') &&
                    window.scrollX===0 && window.scrollY===0 && root.scrollTop===0 &&
                    root.scrollLeft===0 && bounds.x===0 && bounds.y===0 &&
                    Math.abs(bounds.width-innerWidth)<1 && Math.abs(bounds.height-innerHeight)<1 &&
                    document.querySelector('header').getBoundingClientRect().top===0 &&
                    Math.abs(document.querySelector('footer').getBoundingClientRect().bottom-innerHeight)<1;''')

            wait_for(pinned_shell)

            def wheel_panel(selector, button):
                window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--name',
                    '^DeepSeek Harness Desktop$'], text=True).splitlines()[0]
                geometry = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', window], text=True)
                height = int(next(line.split('=')[1] for line in geometry.splitlines() if line.startswith('HEIGHT=')))
                point = script('''const r=document.querySelector(arguments[0]).getBoundingClientRect();
                  return [r.x+Math.min(r.width/2,80),r.y+80,innerHeight];''', [selector])
                subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)
                # Move away first, including when the previous view left the
                # pointer at this exact coordinate. Wait for WebKit to receive
                # the motion, rather than only X11's pointer update.
                subprocess.run(['xdotool', 'mousemove', '--sync', '--window', window, '5', '5'], check=True)
                subprocess.run(['xdotool', 'mousemove', '--sync', '--window', window,
                    str(round(point[0])), str(round(point[1] + height - point[2]))], check=True)
                wait_for(lambda: script('return document.querySelector(arguments[0]).matches(":hover")', [selector]))
                subprocess.run(['xdotool', 'click', '--repeat', '12', '--delay', '50', str(button)], check=True)

            wheel_panel('#messages', 5)
            wait_for(lambda: script('return document.querySelector("#messages").scrollTop') > 0)
            assert script('return document.querySelector("#sidebar").scrollTop') == 0
            wheel_panel('#sidebar', 5)
            wait_for(lambda: script('return document.querySelector("#sidebar").scrollTop') > 0)
            wheel_panel('#messages', 7)
            wait_for(lambda: script('return document.querySelector("#messages").scrollLeft') > 0)
            script('document.querySelector("#messages").focus()')
            shortcut('End')
            wait_for(lambda: script('''const e=document.querySelector('#messages');
              return e.scrollTop+e.clientHeight>=e.scrollHeight-1;'''))
            wheel_panel('#messages', 5)
            assert pinned_shell()
            script('document.querySelector("#messages").scrollLeft=0')
            screenshot('native-scroll-shell.png')

            window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--name',
                '^DeepSeek Harness Desktop$'], text=True).splitlines()[0]
            subprocess.run(['xdotool', 'windowsize', window, '800', '600'], check=True)
            wait_for(lambda: script('return innerWidth') == 800)
            assert pinned_shell()
            width = script('return innerWidth')
            shortcut('ctrl+equal')
            wait_for(lambda: script('return innerWidth') < width)
            assert pinned_shell()
            shortcut('ctrl+0')
            wait_for(lambda: script('return innerWidth') == width)
            shortcut('ctrl+r')
            remote = wait_for(lambda: select_window('Desktop scroll fixture'))
            wait_for(pinned_shell)
            script('location.href="/shell?view=reloaded"')
            wait_for(lambda: request('GET', prefix + '/url').endswith('/shell?view=reloaded'))
            wait_for(pinned_shell)
            print('PASS: fixed document, strict CSP, independent vertical/horizontal panel scrolling, keyboard, resize, zoom and navigation/reload', flush=True)
            subprocess.run(['xdotool', 'windowsize', window, '1080', '780'], check=True)
            local = switch_server()
            connect_fixture('localhost:4317')
            remote = wait_for(lambda: select_window('Harness fixture'))

            # The native reload hook detects that the browser cookie has expired.
            script('document.querySelector("#expire").click()')
            local = wait_for(lambda: select_window('Нужна авторизация'))
            wait_for(lambda: script('return document.querySelector("#server-url").value') == 'http://localhost:4317/')
            connect_fixture('localhost:4317/?token=fixture-token')
            remote = wait_for(lambda: select_window('Harness fixture'))

            # Native menu accelerators switch the visible primary window.
            local = switch_server()
            connect_fixture('localhost:4317')
            remote = wait_for(lambda: select_window('Harness fixture'))
            wait_for(lambda: 'API authenticated' in script('return document.body.innerText'))
            download(Path(profile) / 'native-download.txt', headers=True)
            remote = wait_for(lambda: select_window('Harness fixture'))
            print('PASS: native Save cancellation and file content after reconnect', flush=True)
            print('PASS: expired cookie, retry and Ctrl+L', flush=True)

            # A new application process must propose the clean address and keep cookies.
            request('DELETE', prefix)
            session = None
            subprocess.run(['pkill', '-TERM', '-f', '^' + PROCESS], check=False)
            time.sleep(1)
            created = request('POST', '/session', {'capabilities': {'alwaysMatch': {
                'browserName': 'wry', 'webkitgtk:browserOptions': {'binary': str(BINARY)}
            }}})
            session = created['sessionId']
            prefix = '/session/' + session
            local = wait_for(lambda: select_window('Адрес сервера'))
            wait_for(lambda: script('return document.querySelector("#server-url").value') == 'http://localhost:4317/')
            assert len(request('GET', prefix + '/window/handles')) == 1
            connect_fixture('localhost:4317')
            remote = wait_for(lambda: select_window('Harness fixture'))
            wait_for(lambda: 'API authenticated' in script('return document.body.innerText'))
            print('PASS: clean remembered address, explicit connect and cookies after process restart', flush=True)

            # A connection to a closed port returns a safe error and keeps the form usable.
            local = switch_server()
            connect_fixture('localhost:4318')
            wait_for(lambda: local_message('Проверьте адрес'))
            assert not script('return document.querySelector("#connect").disabled')
            connect_fixture('localhost:4317/forbidden')
            wait_for(lambda: local_message('Сервер отклонил'))
            connect_fixture('https://localhost:4319')
            wait_for(lambda: local_message('Проверьте сертификат'))
            print('PASS: network, 403 and TLS messages', flush=True)

            connect_fixture('localhost:4317/slow')
            wait_for(lambda: script('return !document.querySelector("#cancel").hidden'))
            script('document.querySelector("#cancel").click()')
            wait_for(lambda: not script('return document.querySelector("#connect").disabled'))
            connect_fixture('localhost:4317')
            remote = wait_for(lambda: select_window('Harness fixture'))
            time.sleep(16)
            assert select_window('Harness fixture') == remote
            settings = list(Path(profile + '/config').rglob('settings.json'))
            assert settings and 'fixture-token' not in settings[0].read_text()
            # Select GTK's File -> Reset session with real native pointer input.
            # This also checks that a window created hidden exposes its menu bar.
            from download_linux import screenshot as desktop_screenshot
            desktop_screenshot('native-desktop.png')
            window = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--name',
                '^DeepSeek Harness Desktop$'], text=True).splitlines()[0]
            subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)
            subprocess.run(['xdotool', 'mousemove', '--window', window, '130', '12', 'click', '1'], check=True)
            time.sleep(0.5)
            desktop_screenshot('native-menu.png')
            subprocess.run(['xdotool', 'mousemove', '--window', window, '130', '60', 'click', '1'], check=True)
            wait_for(lambda: len(request('GET', prefix + '/window/handles')) == 1)
            connect_fixture('localhost:4317')
            wait_for(lambda: local_message('Нужна авторизация'))
            print('PASS native GTK: form, token/cookie, API, WebSocket, IPC denial, upload/download, clipboard, Ctrl+L/R, zoom, expiry/reset/retry, cookie restart, network/403/TLS, cancellation, sanitized settings', flush=True)
        finally:
            if session:
                try:
                    request('DELETE', '/session/' + session)
                except (RuntimeError, URLError):
                    pass
            driver.terminate()
            fixture.terminate()
            tls_fixture.terminate()
            subprocess.run(['pkill', '-TERM', '-f', '^' + PROCESS], check=False)
            driver.wait(timeout=10)
            fixture.wait(timeout=10)
            tls_fixture.wait(timeout=10)


if __name__ == '__main__':
    main()
