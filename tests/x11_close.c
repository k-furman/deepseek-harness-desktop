/* Exercise the normal window-manager Close request in the isolated Xvfb test. */
#include <X11/Xlib.h>
#include <assert.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    assert(argc == 2);
    Display *display = XOpenDisplay(NULL);
    assert(display);
    Window window = strtoul(argv[1], NULL, 0);
    Atom protocol = XInternAtom(display, "WM_DELETE_WINDOW", False);
    Atom *supported = NULL;
    int count = 0;
    assert(XGetWMProtocols(display, window, &supported, &count));
    int found = 0;
    for (int i = 0; i < count; i++) found |= supported[i] == protocol;
    XFree(supported);
    assert(found);
    XEvent event = {0};
    event.xclient.type = ClientMessage;
    event.xclient.window = window;
    event.xclient.message_type = XInternAtom(display, "WM_PROTOCOLS", False);
    event.xclient.format = 32;
    event.xclient.data.l[0] = protocol;
    event.xclient.data.l[1] = CurrentTime;
    assert(XSendEvent(display, window, False, NoEventMask, &event));
    XFlush(display);
    XCloseDisplay(display);
    return 0;
}
