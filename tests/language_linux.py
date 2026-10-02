"""Native language/preferences regression against GTK/WebKit in isolated Xvfb."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import URLError
from native_linux import BINARY, PROCESS, ROOT, request, wait_for


def main():
    with tempfile.TemporaryDirectory(prefix='dsh-language-') as profile:
        fixture = subprocess.Popen(['python3', 'tests/fixture_server.py'], cwd=ROOT)
        driver = None
        session = None
        prefix = ''

        def script(code, arguments=None):
            return request('POST', prefix + '/execute/sync', {'script': code, 'args': arguments or []})

        def asynchronous(code, arguments=None):
            return request('POST', prefix + '/execute/async', {'script': code, 'args': arguments or []})

        def select_window(selector):
            for handle in request('GET', prefix + '/window/handles'):
                request('POST', prefix + '/window', {'handle': handle})
                if script('return !!document.querySelector(arguments[0])', [selector]):
                    return handle
            return None

        def visible_windows(title):
            result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^' + title + '$'],
                capture_output=True, text=True)
            return result.stdout.splitlines() if result.returncode == 0 else []

        def shortcut(keys, title='DeepSeek Harness Desktop'):
            window = wait_for(lambda: visible_windows(title))[0]
            subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)
            subprocess.run(['xdotool', 'key', '--clearmodifiers', *keys.split()], check=True)

        def click(selector):
            element = request('POST', prefix + '/element', {'using': 'css selector', 'value': selector})
            identifier = element['element-6066-11e4-a52e-4f735466cecf']
            try:
                return request('POST', prefix + '/element/' + identifier + '/click', {})
            except RuntimeError as error:
                # Closing the selected WebView can complete before WebDriver
                # sends its click response. Verify the remaining handles below.
                if selector != '#close-preferences' or not str(error).startswith('no such window:'):
                    raise

        def stop():
            nonlocal driver, session
            if session:
                try:
                    request('DELETE', prefix)
                except (RuntimeError, URLError):
                    pass
                session = None
            subprocess.run(['pkill', '-TERM', '-f', '^' + PROCESS], check=False)
            if driver:
                driver.terminate()
                driver.wait(timeout=10)
                driver = None

        def start(locale):
            nonlocal driver, session, prefix
            stop()
            env = os.environ.copy()
            env.update(TAURI_WEBVIEW_AUTOMATION='true', XDG_CONFIG_HOME=profile + '/config',
                XDG_DATA_HOME=profile + '/data', XDG_CACHE_HOME=profile + '/cache',
                LANGUAGE=locale, LC_ALL='C.UTF-8', LANG='C.UTF-8')
            driver = subprocess.Popen(['WebKitWebDriver', '--port=4444'], env=env)
            wait_for(lambda: request('GET', '/status')['ready'])
            created = request('POST', '/session', {'capabilities': {'alwaysMatch': {
                'browserName': 'wry', 'webkitgtk:browserOptions': {'binary': str(BINARY)}
            }}})
            session = created['sessionId']
            prefix = '/session/' + session
            return wait_for(lambda: select_window('#connect-form'), seconds=60)

        def open_settings():
            shortcut('ctrl+comma')
            handle = wait_for(lambda: select_window('#language'))
            wait_for(lambda: not script('return document.querySelector("#language").disabled'))
            return handle

        def choose(keys, expected):
            title = script('return document.querySelector("h1").textContent')
            window = wait_for(lambda: visible_windows(title))[0]
            subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)
            geometry = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', window], text=True)
            height = int(next(line.split('=')[1] for line in geometry.splitlines() if line.startswith('HEIGHT=')))
            point = script('''const r=document.querySelector('#language').getBoundingClientRect();
              return [r.x+r.width/2,r.y+r.height/2,innerHeight];''')
            subprocess.run(['xdotool', 'mousemove', '--window', window,
                str(round(point[0])), str(round(point[1] + height - point[2])), 'click', '1'], check=True)
            time.sleep(0.3)
            # Keep the native popup's keyboard grab; refocusing its parent here
            # dismisses the popup before its highlighted option is committed.
            subprocess.run(['xdotool', 'key', '--clearmodifiers', '--delay', '100', *keys.split()], check=True)
            wait_for(lambda: script('return document.querySelector("#language").value') == expected)
            wait_for(lambda: not script('return document.querySelector("#language").disabled'))
            wait_for(lambda: script('return document.querySelector("#preference-status").textContent') in ('Saved', 'Сохранено'))

        def close_settings():
            click('#close-preferences')
            wait_for(lambda: len(request('GET', prefix + '/window/handles')) == 2)

        def native_download(title):
            select_window('#api')
            wait_for(lambda: script('return document.visibilityState') == 'visible')
            with ThreadPoolExecutor(max_workers=1) as clicks:
                clicked = clicks.submit(click, 'a[download]')
                dialog = wait_for(lambda: visible_windows(title))[0]
                subprocess.run(['xdotool', 'windowfocus', '--sync', dialog], check=True)
                subprocess.run(['xdotool', 'key', '--clearmodifiers', 'Escape'], check=True)
                wait_for(lambda: not visible_windows(title))
                clicked.result(timeout=15)

        try:
            local = start('de_DE.UTF-8')
            wait_for(lambda: script('return !document.querySelector("#connect").disabled'))
            assert script('return document.documentElement.lang') == 'en'
            assert script('return document.querySelector("label").textContent') == 'Server address'
            script('document.querySelector("#server-url").value="localhost:4317/?token=fixture-token"')
            preferences = open_settings()
            assert script('return document.querySelector("#language").value') == 'system'
            assert 'English' in script('return document.querySelector("option[value=system]").textContent')
            for command in ['get_snapshot', 'connect', 'cancel_connect', 'open_preferences']:
                outcome = asynchronous('''const done=arguments[arguments.length-1];
                  window.__TAURI_INTERNALS__.invoke(arguments[0],{address:'localhost:4317'})
                    .then(()=>done('allowed'),error=>done(String(error)));''', [command])
                assert any(word in outcome.lower() for word in ('not allowed', 'forbidden', 'denied'))
            choose('End Return', 'ru')
            request('POST', prefix + '/window', {'handle': local})
            wait_for(lambda: script('return document.documentElement.lang') == 'ru')
            assert script('return document.querySelector("#server-url").value').endswith('token=fixture-token')
            request('POST', prefix + '/window', {'handle': preferences})
            click('#close-preferences')
            wait_for(lambda: len(request('GET', prefix + '/window/handles')) == 1)
            print('PASS: native settings open, dropdown switches to Russian, unsent URL retained, settings Close keeps main window', flush=True)
            request('POST', prefix + '/window', {'handle': local})
            script('document.querySelector("#connect-form").requestSubmit()')
            remote = wait_for(lambda: select_window('#api'))
            wait_for(lambda: 'API authenticated' in script('return document.body.innerText'))
            wait_for(lambda: 'WebSocket authenticated' in script('return document.body.innerText'))
            native_download('Сохранить файл')
            print('PASS: connected session and Russian download dialog', flush=True)

            preferences = open_settings()
            invalid = asynchronous('''const done=arguments[arguments.length-1];
              window.__TAURI_INTERNALS__.invoke('set_language',{language:'de'})
                .then(()=>done('allowed'),()=>done('rejected'));''')
            assert invalid == 'rejected'
            assert script('return document.querySelector("#language").value') == 'ru'
            choose('Home Down Return', 'en')
            assert script('return document.documentElement.lang') == 'en'
            artifact = ROOT / 'artifacts/linux'
            # DOM state can precede GTK/WebKit's painted frame in emulation.
            time.sleep(1)
            (artifact / 'native-settings-en.png').write_bytes(base64.b64decode(request('GET', prefix + '/screenshot')))
            from download_linux import screenshot
            screenshot('native-settings-desktop-en.png')
            assert script('return document.body.scrollHeight<=innerHeight')
            close_settings()
            assert select_window('#api') == remote
            assert 'token=' not in request('GET', prefix + '/url')
            for command in ['get_preferences', 'set_language', 'close_preferences', 'open_preferences']:
                outcome = asynchronous('''const done=arguments[arguments.length-1];
                  window.__TAURI_INTERNALS__.invoke(arguments[0],{language:'ru'})
                    .then(()=>done('allowed'),error=>done(String(error)));''', [command])
                assert any(word in outcome.lower() for word in ('not allowed', 'forbidden', 'denied'))
            native_download('Save file')
            time.sleep(1)
            screenshot('native-menu-en.png')
            shortcut('ctrl+l')
            wait_for(lambda: select_window('#connect-form'))
            script('document.querySelector("#server-url").value="localhost:4318";document.querySelector("#connect-form").requestSubmit()')
            wait_for(lambda: 'container' in script('return document.querySelector("#status").textContent'))
            assert script('return document.documentElement.lang') == 'en'
            print('PASS: unsupported system locale -> English, native dropdowns, immediate Russian/English, draft preserved, connected session retained, localized downloads/errors, preference IPC isolation', flush=True)

            local = start('ru_RU.UTF-8')
            wait_for(lambda: script('return !document.querySelector("#connect").disabled'))
            assert script('return document.documentElement.lang') == 'en'
            open_settings()
            choose('Home Return', 'system')
            assert script('return document.documentElement.lang') == 'ru'
            title = script('return document.querySelector("h1").textContent')
            window = visible_windows(title)[0]
            # xdotool windowclose destroys the X drawable, bypassing GTK's Close
            # event. Send the same WM_DELETE_WINDOW request as a window manager.
            close_tool = profile + '/native-close'
            subprocess.run(['cc', 'tests/x11_close.c', '-lX11', '-o', close_tool], check=True)
            subprocess.run([close_tool, window], check=True)
            wait_for(lambda: len(request('GET', prefix + '/window/handles')) == 1)
            request('POST', prefix + '/window', {'handle': local})
            wait_for(lambda: script('return document.documentElement.lang') == 'ru')
            # Reopening after native Close must keep the main app and menu working.
            open_settings()
            assert script('return document.querySelector("#language").value') == 'system'
            click('#close-preferences')
            wait_for(lambda: len(request('GET', prefix + '/window/handles')) == 1)

            start('zh_CN.UTF-8')
            wait_for(lambda: script('return !document.querySelector("#connect").disabled'))
            assert script('return document.documentElement.lang') == 'en'
            paths = list(Path(profile + '/config').rglob('settings.json'))
            assert paths and json.loads(paths[0].read_text())['language'] == 'system'
            assert 'fixture-token' not in paths[0].read_text()
            print('PASS: saved override survives OS locale change/restart, System follows OS with English fallback, native preferences Close preserves main window, sanitized settings', flush=True)
        except Exception:
            from download_linux import screenshot
            screenshot('native-settings-debug.png')
            raise
        finally:
            stop()
            fixture.terminate()
            fixture.wait(timeout=10)


if __name__ == '__main__':
    main()
