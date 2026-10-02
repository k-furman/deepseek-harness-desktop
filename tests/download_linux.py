"""Test native downloads outside a WebDriver-controlled WebView, in Xvfb only."""
import os
import signal
import ctypes
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from fixture_server import Handler, ThreadingHTTPServer


def wait(callback, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        result = callback()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError('Native download condition timed out')


def windows(title):
    result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^' + title + '$'],
        capture_output=True, text=True)
    return result.stdout.splitlines() if result.returncode == 0 else []


def key(*keys):
    subprocess.run(['xdotool', 'key', '--clearmodifiers', '--delay', '100', *keys], check=True)


def paste(text):
    # Paste a whole value: emulated X11 key synthesis can drop characters.
    gtk = ctypes.CDLL('libgtk-3.so.0')
    gtk.gtk_init(None, None)
    gdk = ctypes.CDLL('libgdk-3.so.0')
    gdk.gdk_atom_intern_static_string.restype = ctypes.c_void_p
    gtk.gtk_clipboard_get.argtypes = [ctypes.c_void_p]
    gtk.gtk_clipboard_get.restype = ctypes.c_void_p
    clipboard = gtk.gtk_clipboard_get(gdk.gdk_atom_intern_static_string(b'CLIPBOARD'))
    gtk.gtk_clipboard_set_text.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    gtk.gtk_clipboard_set_text(clipboard, text.encode(), -1)
    process = subprocess.Popen(['xdotool', 'key', '--clearmodifiers', 'ctrl+v'])
    deadline = time.monotonic() + 5
    while process.poll() is None or time.monotonic() < deadline:
        while gtk.gtk_events_pending():
            gtk.gtk_main_iteration_do(False)
        time.sleep(0.01)
    assert process.returncode == 0


def screenshot(name='native-download-debug.png'):
    gtk = ctypes.CDLL('libgtk-3.so.0')
    gtk.gtk_init(None, None)
    gdk = ctypes.CDLL('libgdk-3.so.0')
    gdk.gdk_get_default_root_window.restype = ctypes.c_void_p
    root = gdk.gdk_get_default_root_window()
    gdk.gdk_window_get_width.argtypes = [ctypes.c_void_p]
    gdk.gdk_window_get_height.argtypes = [ctypes.c_void_p]
    gdk.gdk_pixbuf_get_from_window.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4
    gdk.gdk_pixbuf_get_from_window.restype = ctypes.c_void_p
    pixbuf = gdk.gdk_pixbuf_get_from_window(root, 0, 0, gdk.gdk_window_get_width(root), gdk.gdk_window_get_height(root))
    library = ctypes.CDLL('libgdk_pixbuf-2.0.so.0')
    library.gdk_pixbuf_savev.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    directory = Path(__file__).resolve().parents[1] / 'artifacts/linux'
    directory.mkdir(parents=True, exist_ok=True)
    assert library.gdk_pixbuf_savev(pixbuf, os.fsencode(directory / name), b'png', None, None, None)


def main():
    binary = os.environ.get('DSH_TEST_BINARY', str(Path(__file__).resolve().parents[1] / 'src-tauri/target/release/deepseek-harness-desktop'))
    loaded = threading.Event()

    class Fixture(Handler):
        def do_GET(self):
            if self.path == '/download':
                print('Native fixture download requested; authorized=' + str(self.authorized()), flush=True)
            if self.path == '/api/status' and self.authorized():
                loaded.set()
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 4317), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='dsh-download-') as profile:
        env = os.environ.copy()
        env.pop('TAURI_WEBVIEW_AUTOMATION', None)
        env.update(XDG_CONFIG_HOME=profile + '/config', XDG_DATA_HOME=profile + '/data', XDG_CACHE_HOME=profile + '/cache')
        env.update(LANGUAGE='ru_RU', LC_ALL='C.UTF-8', LANG='C.UTF-8')
        # AppImage's runtime can spawn AppRun; keep cleanup scoped to our process group.
        process = subprocess.Popen([binary], env=env, start_new_session=True)
        try:
            window = wait(lambda: windows('DeepSeek Harness Desktop'))[0]
            subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)
            time.sleep(5)
            key('ctrl+l')
            time.sleep(1)
            subprocess.run(['xdotool', 'mousemove', '--window', window, '500', '430', 'click', '1'], check=True)
            key('ctrl+a')
            time.sleep(0.5)
            paste('localhost:4317/?token=fixture-token')
            key('Return')
            assert loaded.wait(20), 'Fixture page did not authenticate'
            time.sleep(1)
            window = wait(lambda: windows('DeepSeek Harness Desktop'))[0]
            subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)
            # Focus the page, then walk its labelled form controls to Download.
            subprocess.run(['xdotool', 'mousemove', '--window', window, '900', '700', 'click', '1'], check=True)
            key('Tab', 'Tab', 'Tab', 'Return')
            dialog = wait(lambda: windows('Сохранить файл'))[0]
            subprocess.run(['xdotool', 'windowfocus', '--sync', dialog], check=True)
            key('Escape')
            wait(lambda: not windows('Сохранить файл'))
            key('ctrl+l')
            loaded.clear()
            window = wait(lambda: windows('DeepSeek Harness Desktop'))[0]
            subprocess.run(['xdotool', 'mousemove', '--window', window, '500', '430', 'click', '1'], check=True)
            key('ctrl+a')
            time.sleep(0.5)
            paste('localhost:4317')
            key('Return')
            assert loaded.wait(20), 'Cookie reconnect failed'
            time.sleep(1)
            window = wait(lambda: windows('DeepSeek Harness Desktop'))[0]
            subprocess.run(['xdotool', 'windowfocus', '--sync', window], check=True)
            subprocess.run(['xdotool', 'mousemove', '--window', window, '900', '700', 'click', '1'], check=True)
            key('Tab', 'Tab', 'Tab', 'Return')
            dialog = wait(lambda: windows('Сохранить файл'))[0]
            subprocess.run(['xdotool', 'windowfocus', '--sync', dialog], check=True)
            destination = Path(profile) / 'fixture.txt'
            screenshot('native-save-dialog.png')
            key('ctrl+l')
            time.sleep(0.5)
            key('ctrl+a')
            paste(str(destination))
            screenshot('native-save-path.png')
            key('Return')
            time.sleep(0.3)
            if windows('Сохранить файл'):
                key('Return')
            wait(lambda: destination.exists() and destination.read_bytes() == b'Harness desktop download fixture\n')
            print('PASS native download without WebDriver: authentication, Cancel, cookie reconnect, Save and file content', flush=True)
        except Exception:
            screenshot()
            raise
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
