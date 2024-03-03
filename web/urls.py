from litestar import Request


def index_url(request: Request) -> str:
    return request.app.route_reverse('index')


def event_url(request: Request, event_id: str) -> str:
    return request.app.route_reverse('show-event', event_id=event_id)


def login_url(request: Request, event_id: str, screen_id: str) -> str:
    return request.app.route_reverse('login', event_id=event_id, screen_id=screen_id)


def screen_url(request: Request, event_id: str, screen_id: str) -> str:
    return request.app.route_reverse('show-screen', event_id=event_id, screen_id=screen_id)


def rotator_url(request: Request, event_id: str, rotator_id: str) -> str:
    return request.app.route_reverse(
        'show-rotator', event_id=event_id, rotator_id=rotator_id)


def rotator_screen_url(request: Request, event_id: str, rotator_id: str, screen_index: int) -> str:
    return request.app.route_reverse(
        'show-rotator-screen', event_id=event_id, rotator_id=rotator_id, screen_index=screen_index)
